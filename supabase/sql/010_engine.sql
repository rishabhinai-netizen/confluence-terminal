-- Confluence Terminal v2 engine (12 Oct 2026). Re-measures every rule nightly from raw data.
-- Conventions (identical to research/rs.py):
--  * entry = close of the first trading session strictly AFTER the calendar day the information became public;
--  * react = entry close / close of the session before the announcement day (two-session reaction);
--  * excess = stock return - equal-weight liquid-universe return over the same sessions;
--  * universe = stocks with average turnover >= Rs 2 cr over the previous 20 sessions; daily returns clipped at +-40%.

create table if not exists ct_days (i int primary key, d date unique not null);
create table if not exists ct_mkt (d date primary key, i int, r numeric, idx numeric, sma50 numeric, up boolean, n int);
create table if not exists ct_ev (
  kind text not null, id text not null, isin text not null, ts timestamptz, pub_d date,
  entry_i int, entry_d date, pre_c real, entry_c real, react numeric, a jsonb,
  r5 numeric, r20 numeric, r40 numeric, r60 numeric, x5 numeric, x20 numeric, x40 numeric, x60 numeric,
  up boolean, rules text[] default '{}', primary key (kind, id));
create index if not exists ct_ev_isin on ct_ev(isin, ts desc);
create index if not exists ct_ev_entry on ct_ev(entry_d desc);
alter table ct_days enable row level security; alter table ct_mkt enable row level security; alter table ct_ev enable row level security;

create or replace function ct_refresh_market() returns jsonb language plpgsql security definer set search_path = public as $$
declare n int;
begin
  insert into ct_days(i, d) select row_number() over (order by d)::int, d from (select distinct d from ct_prices where d >= '2025-01-01') z
  on conflict (i) do update set d = excluded.d;
  insert into ct_mkt(d, i, r, n)
  select p.d, dd.i, avg(least(greatest(p.c / p.pc - 1, -0.4), 0.4)) filter (where p.t20 >= 2 and p.pc > 0),
         count(*) filter (where p.t20 >= 2 and p.pc > 0)
  from (select isin, d, c, lag(c) over w pc, avg(c::numeric * v / 1e7) over (partition by isin order by d rows between 20 preceding and 1 preceding) t20
        from ct_prices window w as (partition by isin order by d)) p
  join ct_days dd on dd.d = p.d group by p.d, dd.i
  on conflict (d) do update set i = excluded.i, r = excluded.r, n = excluded.n;
  update ct_mkt set r = 0 where r is null or i = 1;
  update ct_mkt m set idx = z.idx from (select d, exp(sum(ln(1 + r)) over (order by d)) idx from ct_mkt) z where z.d = m.d;
  update ct_mkt m set sma50 = z.s, up = m.idx > z.s from (select d, avg(idx) over (order by d rows between 49 preceding and current row) s, count(*) over (order by d rows between 49 preceding and current row) k from ct_mkt) z where z.d = m.d and z.k >= 50;
  select count(*) into n from ct_mkt;
  return jsonb_build_object('days', n, 'last', (select max(d) from ct_mkt));
end $$;

-- close of an ISIN at session index i (walks back up to 10 days over suspensions)
create or replace function ct_px(p_isin text, p_i int) returns real language sql stable set search_path = public as $$
  select p.c from ct_days dd join ct_prices p on p.isin = p_isin and p.d <= dd.d and p.d > dd.d - 10
  where dd.i = p_i order by p.d desc limit 1 $$;

-- (re)compute prices / forward returns / rules for events; p_kind null = all kinds
create or replace function ct_score_events(p_kind text default null, p_since date default '2000-01-01') returns int language plpgsql security definer set search_path = public as $$
declare n int; mx int;
begin
  select max(i) into mx from ct_days;
  update ct_ev e set entry_i = (select min(i) from ct_days where d > e.pub_d)
   where (p_kind is null or kind = p_kind) and pub_d >= p_since;
  update ct_ev e set entry_d = dd.d from ct_days dd where dd.i = e.entry_i and (p_kind is null or e.kind = p_kind) and e.pub_d >= p_since;
  update ct_ev e set entry_c = ct_px(e.isin, e.entry_i), pre_c = ct_px(e.isin, e.entry_i - 2)
   where (p_kind is null or kind = p_kind) and pub_d >= p_since and entry_i is not null;
  update ct_ev e set react = case when pre_c > 0 and entry_c > 0 then entry_c / pre_c - 1 end,
     up = (select m.up from ct_mkt m where m.i = e.entry_i)
   where (p_kind is null or kind = p_kind) and pub_d >= p_since;
  update ct_ev e set
     r5  = case when e.entry_i + 5  <= mx then ct_px(e.isin, e.entry_i + 5)  / e.entry_c - 1 end,
     r20 = case when e.entry_i + 20 <= mx then ct_px(e.isin, e.entry_i + 20) / e.entry_c - 1 end,
     r40 = case when e.entry_i + 40 <= mx then ct_px(e.isin, e.entry_i + 40) / e.entry_c - 1 end,
     r60 = case when e.entry_i + 60 <= mx then ct_px(e.isin, e.entry_i + 60) / e.entry_c - 1 end
   where (p_kind is null or kind = p_kind) and pub_d >= p_since and entry_c > 0;
  update ct_ev e set
     x5  = e.r5  - ((select idx from ct_mkt where i = e.entry_i + 5)  / m0.idx - 1),
     x20 = e.r20 - ((select idx from ct_mkt where i = e.entry_i + 20) / m0.idx - 1),
     x40 = e.r40 - ((select idx from ct_mkt where i = e.entry_i + 40) / m0.idx - 1),
     x60 = e.r60 - ((select idx from ct_mkt where i = e.entry_i + 60) / m0.idx - 1)
   from ct_mkt m0 where m0.i = e.entry_i and (p_kind is null or e.kind = p_kind) and e.pub_d >= p_since;
  -- rules (definitions documented in research/README.md; every one was tested out of sample before being added)
  update ct_ev e set rules = array_remove(array[
     case when kind = 'result' and (a->>'pat')::numeric >= 25 and (a->>'rev')::numeric >= 15 and react >= 0.03 then 'drift_buy' end,
     case when kind = 'result' and ((a->>'verdict') = 'MISS' or (a->>'pat')::numeric <= -10) and react <= -0.03 then 'avoid_miss_fall' end,
     case when kind = 'result' and (a->>'bsh') = 'STRESSED' then 'avoid_stressed' end,
     case when kind = 'concall' and (a->>'guid') = 'CUT' then 'avoid_guidance_cut' end,
     case when kind = 'concall' and (a->>'guid') = 'RAISED' then 'guidance_raised' end,
     case when kind = 'concall' and (a->>'deliv') = 'MISSED' then 'guidance_missed' end,
     case when kind = 'smart' and (a->>'src') = 'BULK' and (a->>'side') in ('BUY','SELL') and (a->>'pct_mcap')::numeric >= 0.1 then 'in_play_bulk' end,
     case when kind = 'smart' and (a->>'src') = 'BULK' and (a->>'side') = 'HFT' and (a->>'pct_mcap')::numeric >= 0.1 then 'flag_bulk_churn' end,
     case when kind = 'smart' and (a->>'src') = 'INSIDER' and (a->>'side') = 'SELL' and not coalesce((a->>'promoter')::boolean, false) then 'flag_insider_sell' end,
     case when kind = 'smart' and (a->>'src') = 'INSIDER' and (a->>'side') = 'BUY' and coalesce((a->>'promoter')::boolean, false) then 'promoter_buy' end
   ]::text[], null)
   where (p_kind is null or kind = p_kind) and pub_d >= p_since;
  get diagnostics n = row_count;
  return n;
end $$;

-- load / refresh events from the source tables
create or replace function ct_build_events(p_since date default '2000-01-01') returns jsonb language plpgsql security definer set search_path = public as $$
declare nr int; nc int; ns int;
begin
  insert into ct_ev(kind, id, isin, ts, pub_d, a)
  select 'result', r.id, r.isin, r.announced_at, (r.announced_at at time zone 'Asia/Kolkata')::date,
         jsonb_strip_nulls(jsonb_build_object('pat', (r.raw->>'patYoyGrowth')::numeric, 'rev', (r.raw->>'revenueYoyGrowth')::numeric,
           'opm_bps', (r.raw->>'opmYoyBps')::numeric, 'verdict', r.verdict, 'pead', r.pead_label, 'bsh', r.bsh, 'q', 'Q' || r.q || 'FY' || r.fy,
           'type', r.raw->>'type'))
  from ct_es_results r where r.isin is not null and r.announced_at is not null and (r.announced_at at time zone 'Asia/Kolkata')::date >= p_since
  on conflict (kind, id) do update set isin = excluded.isin, ts = excluded.ts, pub_d = excluded.pub_d, a = excluded.a;
  get diagnostics nr = row_count;
  insert into ct_ev(kind, id, isin, ts, pub_d, a)
  select 'concall', c.id, c.isin, c.concall_at, (c.concall_at at time zone 'Asia/Kolkata')::date,
         jsonb_strip_nulls(jsonb_build_object('guid', c.guidance_revision, 'deliv', c.guidance_delivery, 'tone', c.tone, 'candor', c.candor,
           'eq', c.earnings_quality, 'analyst', c.analyst_sentiment, 'story', c.story_type, 'q', 'Q' || c.q || 'FY' || c.fy))
  from ct_es_concalls c where c.isin is not null and c.concall_at is not null and (c.concall_at at time zone 'Asia/Kolkata')::date >= p_since
  on conflict (kind, id) do update set isin = excluded.isin, ts = excluded.ts, pub_d = excluded.pub_d, a = excluded.a;
  get diagnostics nc = row_count;
  insert into ct_ev(kind, id, isin, ts, pub_d, a)
  select 'smart', s.id, s.isin, coalesce(s.raw->>'disclosureDate', s.raw->>'dealDate')::date, coalesce(s.raw->>'disclosureDate', s.raw->>'dealDate')::date,
         jsonb_strip_nulls(jsonb_build_object('src', s.source, 'side', s.side, 'cr', round(abs(s.net_value) / 1e7, 2),
           'pct_mcap', case when (s.raw->>'marketCap')::numeric > 0 then round(abs(s.net_value) / 1e7 / (s.raw->>'marketCap')::numeric * 100, 3) end,
           'promoter', coalesce(s.raw->>'personCategory', '') ilike '%promoter%', 'who', s.raw->>'topCounterparty', 'cat', s.raw->>'personCategory'))
  from ct_es_smart s where s.isin is not null and coalesce(s.raw->>'disclosureDate', s.raw->>'dealDate')::date >= greatest(p_since, '2025-01-01')
  on conflict (kind, id) do update set a = excluded.a, ts = excluded.ts, pub_d = excluded.pub_d;
  get diagnostics ns = row_count;
  perform ct_score_events(null, p_since);
  return jsonb_build_object('results', nr, 'concalls', nc, 'smart', ns);
end $$;

-- evidence table: every rule vs its own baseline (all events of that kind), overall / by regime / recent.
-- Readers use only rows with the latest computed_at (rows of retired rules just go stale).
create or replace function ct_refresh_stats() returns int language plpgsql security definer set search_path = public as $$
declare n int; stamp timestamptz := clock_timestamp();
begin
  with base as (
    select kind, unnest(rules || array['all_' || kind]) sig, up, entry_d, x20, x60, x5
    from ct_ev where entry_i is not null and valid),
  per as (
    select sig, kind, h, period, x from (
      select sig, kind, 5 h, x5 x, entry_d, up from base union all
      select sig, kind, 20, x20, entry_d, up from base union all
      select sig, kind, 60, x60, entry_d, up from base) z
    cross join lateral (values ('all'), (case when up then 'mkt_up' else 'mkt_down' end),
                               (case when entry_d >= current_date - 270 then 'last_9m' end)) pp(period)
    where x is not null and period is not null)
  insert into ct_signal_stats(signal, family, horizon, period, n, hit, med_excess, mean_excess, p25, p75, computed_at)
  select sig, kind, h, period, count(*), round(avg((x > 0)::int) * 100, 1),
         round((percentile_cont(0.5) within group (order by x) * 100)::numeric, 2),
         round((avg(least(greatest(x, -0.6), 1.5)) * 100)::numeric, 2),
         round((percentile_cont(0.25) within group (order by x) * 100)::numeric, 2),
         round((percentile_cont(0.75) within group (order by x) * 100)::numeric, 2), stamp
  from per group by sig, kind, h, period having count(*) >= 10
  on conflict (signal, horizon, period) do update set family = excluded.family, n = excluded.n, hit = excluded.hit, med_excess = excluded.med_excess,
     mean_excess = excluded.mean_excess, p25 = excluded.p25, p75 = excluded.p75, computed_at = excluded.computed_at;
  get diagnostics n = row_count;
  return n;
end $$;

-- v1.1 (12 Oct 2026): late re-filings. Results filed > 120 days after quarter end are restatements, not news.
alter table ct_ev add column if not exists valid boolean default true;
create or replace function ct_qend(q int, fy int) returns date language sql immutable as $$
  select case q when 1 then make_date(fy - 1, 6, 30) when 2 then make_date(fy - 1, 9, 30) when 3 then make_date(fy - 1, 12, 31) else make_date(fy, 3, 31) end $$;
create or replace function ct_flag_late() returns int language plpgsql security definer set search_path = public as $$
declare n int;
begin
  update ct_ev e set valid = (e.pub_d <= ct_qend(r.q, r.fy) + 120)
  from ct_es_results r where e.kind = 'result' and r.id = e.id;
  update ct_ev set rules = '{}' where valid = false and rules <> '{}';
  get diagnostics n = row_count;
  return n;
end $$;
create or replace function ct_latest_result(p_isin text) returns setof ct_es_results language sql stable set search_path = public as $$
  select * from ct_es_results where isin = p_isin and announced_at is not null and (announced_at at time zone 'Asia/Kolkata')::date <= ct_qend(q, fy) + 120
  order by fy desc, q desc, announced_at desc limit 2 $$;
-- (ct_refresh_stats now reads only valid events: "where entry_i is not null and valid")
