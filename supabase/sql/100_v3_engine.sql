-- Confluence Terminal v3 engine (13 Oct 2026): "Results Leaders" strategy.
-- Research: research/README.md (v3). Python reference implementation: research/v3/*.py
-- Rules
--   Universe   : results filed 0-120 days after quarter end; mcap (point-in-time) >= Rs 1,000 cr; 20-day median turnover >= Rs 5 cr
--   Features   : growth  = rev YoY, PAT YoY, EPS change vs price (SUE-p), OPM change (bps)
--                trend   = vs 200-day avg, distance from 52w high, 200-day avg slope (20 sessions), 120-session excess return before results
--                reaction= stock vs market from the close 2 sessions before the first post-result close, to that close
--   Score      : each feature ranked against the PREVIOUS season's distribution; score = (2*growth + trend + reaction)/4;
--                pr = score ranked against the previous season's scores
--   Buy        : pr >= 0.90, not guidance CUT, not balance sheet STRESSED; within 10 sessions of the first post-result close;
--                15 slots; new position size = (1/15) x market gauge; highest score first
--   Market gauge (vote of 3, known the evening before): equal-weight index > its 100-day avg; % stocks above 50-day EMA > 50;
--                new 52-week highs > new lows  -> 0 / 1/3 / 2/3 / 1
--   Exit       : 60 sessions after entry (no stop: every stop tested lowered returns)
--   Costs      : 0.3% per side in all simulations

create table if not exists ct_days3 (i int primary key, d date unique not null);
create table if not exists ct_mkt3 (d date primary key, i int, r numeric, idx numeric, sma100 numeric, up boolean, n int);
alter table ct_days3 enable row level security; alter table ct_mkt3 enable row level security;
create table if not exists ct_breadth (d date primary key, br50 numeric, br200 numeric, hi52 numeric, lo52 numeric);
create table if not exists ct_ev3 (
  id text primary key, isin text not null, qn int not null, pub_d date, ei int, c0 real, cpre real,
  react_x numeric, rev_yoy numeric, pat_yoy numeric, sue_p numeric, opm_bps numeric,
  above200 numeric, off_hi numeric, sma200_up numeric, run120 numeric, mcap_pit numeric, turn20 numeric,
  g_growth numeric, g_trend numeric, g_react numeric, score numeric, pr numeric, tradeable boolean, excl text, computed_at timestamptz default now());
create index if not exists ct_ev3_qn on ct_ev3(qn); create index if not exists ct_ev3_ei on ct_ev3(ei);
create table if not exists ct_model_pos (ev_id text primary key, isin text not null, entry_i int, entry_d date, entry_c real, last_c real, w numeric, score numeric, open boolean default true, exit_d date);
create index if not exists ct_model_pos_open on ct_model_pos(open, isin);
create table if not exists ct_model_trade (id bigint generated always as identity primary key, isin text, ev_id text, entry_d date, exit_d date,
  entry_c real, exit_c real, w numeric, ret numeric, why text, days int);
create table if not exists ct_model_day (d date primary key, i int, r numeric, equity numeric, n int, gauge numeric, buys int, sells int);
create table if not exists ct_model_orders (d date primary key, buys jsonb, sells jsonb, gauge numeric);   -- decisions taken at close d, executed next close
alter table ct_breadth enable row level security; alter table ct_ev3 enable row level security; alter table ct_model_pos enable row level security;
alter table ct_model_trade enable row level security; alter table ct_model_day enable row level security; alter table ct_model_orders enable row level security;

create or replace function ct_day3(p_i int) returns date language sql stable set search_path = public as $$ select d from ct_days3 where i = p_i $$;
create or replace function ct_px3(p_isin text, p_i int) returns real language sql stable set search_path = public as $$
  select p.c from ct_days3 dd join ct_prices p on p.isin = p_isin and p.d <= dd.d and p.d > dd.d - 10 where dd.i = p_i order by p.d desc limit 1 $$;

-- market index (equal weight, daily returns clipped +-40%); universe = turnover >= Rs 2 cr, or price >= 20 where volume is missing (2024)
create or replace function ct_v3_market() returns jsonb language plpgsql security definer set search_path = public as $$
declare n int;
begin
  insert into ct_days3(i, d) select row_number() over (order by d)::int, d from (select distinct d from ct_prices where d >= '2024-01-01') z
  on conflict (i) do update set d = excluded.d;
  insert into ct_mkt3(d, i, r, n)
  select p.d, dd.i, avg(least(greatest(p.c / p.pc - 1, -0.4), 0.4)) filter (where p.pc > 0 and (p.t20 >= 2 or (p.t20 is null and p.pc >= 20))),
         count(*) filter (where p.pc > 0 and (p.t20 >= 2 or (p.t20 is null and p.pc >= 20)))
  from (select isin, d, c, lag(c) over w pc, avg(c::numeric * v / 1e7) over (partition by isin order by d rows between 20 preceding and 1 preceding) t20
        from ct_prices window w as (partition by isin order by d)) p
  join ct_days3 dd on dd.d = p.d group by p.d, dd.i
  on conflict (d) do update set i = excluded.i, r = excluded.r, n = excluded.n;
  update ct_mkt3 set r = 0 where r is null or i = 1;
  update ct_mkt3 m set idx = z.idx from (select d, exp(sum(ln(1 + r)) over (order by d)) idx from ct_mkt3) z where z.d = m.d;
  update ct_mkt3 m set sma100 = z.s, up = m.idx > z.s from (select d, avg(idx) over (order by d rows between 99 preceding and current row) s,
     count(*) over (order by d rows between 99 preceding and current row) k from ct_mkt3) z where z.d = m.d and z.k >= 100;
  -- breadth from the latest StockScans snapshot (last ~260 sessions)
  insert into ct_breadth(d, br50, br200, hi52, lo52)
  select (x->>0)::date, (x->>3)::numeric, null, null, null
  from ct_snapshot s, jsonb_array_elements(s.body->'p_a_ema_50d') x where s.k = 'ss_breadth' and s.d = (select max(d) from ct_snapshot where k = 'ss_breadth')
  on conflict (d) do update set br50 = excluded.br50;
  update ct_breadth b set hi52 = (x->>3)::numeric from ct_snapshot s, jsonb_array_elements(s.body->'p_l_5_52wh') x
   where s.k = 'ss_breadth' and s.d = (select max(d) from ct_snapshot where k = 'ss_breadth') and (x->>0)::date = b.d;
  update ct_breadth b set lo52 = (x->>3)::numeric from ct_snapshot s, jsonb_array_elements(s.body->'p_l_5_52wl') x
   where s.k = 'ss_breadth' and s.d = (select max(d) from ct_snapshot where k = 'ss_breadth') and (x->>0)::date = b.d;
  update ct_breadth b set br200 = (x->>3)::numeric from ct_snapshot s, jsonb_array_elements(s.body->'p_a_ema_200d') x
   where s.k = 'ss_breadth' and s.d = (select max(d) from ct_snapshot where k = 'ss_breadth') and (x->>0)::date = b.d;
  select count(*) into n from ct_mkt3;
  return jsonb_build_object('days', n, 'last', (select max(d) from ct_mkt3));
end $$;

-- market gauge at session i (0, 1/3, 2/3, 1); breadth carried forward over missing days
create or replace function ct_gauge(p_i int) returns numeric language sql stable set search_path = public as $$
  select ((m.idx > m.sma100)::int + coalesce((b.br50 > 50)::int, 0) + coalesce((b.hi52 > b.lo52)::int, 0))::numeric / 3
  from ct_mkt3 m left join lateral (select * from ct_breadth where d <= m.d order by d desc limit 1) b on true where m.i = p_i $$;

-- percentile of v within a sorted array (fraction of reference values <= v)
create or replace function ct_pr(v numeric, arr numeric[]) returns numeric language plpgsql immutable as $$
declare lo int := 1; hi int := coalesce(array_length(arr, 1), 0); mid int;
begin
  if v is null or hi = 0 then return null; end if;
  while lo <= hi loop mid := (lo + hi) / 2; if arr[mid] <= v then lo := mid + 1; else hi := mid - 1; end if; end loop;
  return (lo - 1)::numeric / array_length(arr, 1);
end $$;

-- 1) features for every result in seasons >= p_qn (point-in-time; needs prices around the event)
create or replace function ct_v3_features(p_qn int) returns int language plpgsql security definer set search_path = public as $$
declare n int;
begin
  perform set_config('statement_timeout', '600s', true);
  insert into ct_ev3(id, isin, qn, pub_d, ei, c0, cpre, react_x, rev_yoy, pat_yoy, sue_p, opm_bps, above200, off_hi, sma200_up, run120, mcap_pit, turn20, computed_at)
  with ev as (
    select r.*, (r.ts at time zone 'Asia/Kolkata')::date pub_d from ct_res r
    where r.qn >= p_qn and r.ts is not null and r.isin like 'IN%'
      and (r.ts at time zone 'Asia/Kolkata')::date between ct_qend(r.q, r.fy) and ct_qend(r.q, r.fy) + 120
      and exists (select 1 from ct_prices p where p.isin = r.isin)),
  ev1 as (select distinct on (isin, qn) * from ev order by isin, qn, ts),
  e2 as (select ev1.*, (select min(i) from ct_days3 where d > ev1.pub_d) ei from ev1)
  select e2.id, e2.isin, e2.qn, e2.pub_d, e2.ei, c0.c, cp.c,
     case when c0.c > 0 and cp.c > 0 then c0.c / cp.c - 1 - (m0.idx / m2.idx - 1) end,
     e2.rev_yoy, e2.pat_yoy,
     case when cp.c > 0 and l4.eps is not null then least(greatest((e2.eps - l4.eps) / cp.c * 400, -20), 20) end,
     e2.opm_bps,
     case when w.a200 > 0 then c0.c / w.a200 - 1 end, case when w.h250 > 0 then c0.c / w.h250 - 1 end,
     case when w2.a200 > 0 then w.a200 / w2.a200 - 1 end,
     case when cp.c > 0 and c122.c > 0 then cp.c / c122.c - 1 - (m2.idx / m122.idx - 1) end,
     mc.mcap * cp.c / nullif(lc.c, 0), tv.t20, now()
  from e2
  left join lateral (select ct_px3(e2.isin, e2.ei) c) c0 on true
  left join lateral (select ct_px3(e2.isin, e2.ei - 2) c) cp on true
  left join lateral (select ct_px3(e2.isin, e2.ei - 122) c) c122 on true
  left join ct_mkt3 m0 on m0.i = e2.ei left join ct_mkt3 m2 on m2.i = e2.ei - 2 left join ct_mkt3 m122 on m122.i = e2.ei - 122
  left join lateral (select eps from ct_res x where x.isin = e2.isin and x.qn = e2.qn - 4 order by ts limit 1) l4 on true
  left join lateral (select case when count(*) >= 120 then avg(c) filter (where p.d > ct_day3(greatest(e2.ei - 200, 1))) end a200, case when count(*) >= 120 then max(c) end h250
                     from ct_prices p where p.isin = e2.isin and p.d >= ct_day3(greatest(e2.ei - 249, 1)) and p.d <= ct_day3(e2.ei)) w on true
  left join lateral (select case when count(*) >= 120 then avg(c) end a200 from ct_prices p where p.isin = e2.isin and p.d >= ct_day3(greatest(e2.ei - 219, 1)) and p.d <= ct_day3(e2.ei - 20) and e2.ei > 140) w2 on true
  left join lateral (select mcap_now mcap from ct_res x where x.isin = e2.isin and x.mcap_now is not null order by qn desc, ts desc limit 1) mc on true
  left join lateral (select c from ct_prices p where p.isin = e2.isin order by d desc limit 1) lc on true
  left join lateral (select percentile_cont(0.5) within group (order by c::numeric * v / 1e7) t20 from ct_prices p
                     where p.isin = e2.isin and p.v is not null and p.d > ct_day3(e2.ei - 20) and p.d <= ct_day3(e2.ei)) tv on true
  on conflict (id) do update set ei = excluded.ei, c0 = excluded.c0, cpre = excluded.cpre, react_x = excluded.react_x, rev_yoy = excluded.rev_yoy,
     pat_yoy = excluded.pat_yoy, sue_p = excluded.sue_p, opm_bps = excluded.opm_bps, above200 = excluded.above200, off_hi = excluded.off_hi,
     sma200_up = excluded.sma200_up, run120 = excluded.run120, mcap_pit = excluded.mcap_pit, turn20 = excluded.turn20, computed_at = now();
  get diagnostics n = row_count;
  return n;
end $$;

-- 2) season-relative scores (reference = previous season; falls back to the two seasons before if thin)
create or replace function ct_v3_score(p_qn int) returns int language plpgsql security definer set search_path = public as $$
declare q int; n int := 0; k int; ref record;
begin
  for q in select distinct qn from ct_ev3 where qn >= p_qn order by 1 loop
    select
      (select array_agg(rev_yoy order by rev_yoy) from ct_ev3 where qn = q - 1 and rev_yoy is not null) a_rev,
      (select array_agg(pat_yoy order by pat_yoy) from ct_ev3 where qn = q - 1 and pat_yoy is not null) a_pat,
      (select array_agg(sue_p order by sue_p) from ct_ev3 where qn = q - 1 and sue_p is not null) a_sue,
      (select array_agg(opm_bps order by opm_bps) from ct_ev3 where qn = q - 1 and opm_bps is not null) a_opm,
      (select array_agg(above200 order by above200) from ct_ev3 where qn = q - 1 and above200 is not null) a_a200,
      (select array_agg(off_hi order by off_hi) from ct_ev3 where qn = q - 1 and off_hi is not null) a_hi,
      (select array_agg(sma200_up order by sma200_up) from ct_ev3 where qn = q - 1 and sma200_up is not null) a_up,
      (select array_agg(run120 order by run120) from ct_ev3 where qn = q - 1 and run120 is not null) a_run,
      (select array_agg(react_x order by react_x) from ct_ev3 where qn = q - 1 and react_x is not null) a_rx,
      (select count(*) from ct_ev3 where qn = q - 1) nref
    into ref;
    if ref.nref < 200 then continue; end if;
    update ct_ev3 e set
      g_growth = (select avg(x) from unnest(array[ct_pr(e.rev_yoy, ref.a_rev), ct_pr(e.pat_yoy, ref.a_pat), ct_pr(e.sue_p, ref.a_sue), ct_pr(e.opm_bps, ref.a_opm)]) x),
      g_trend  = (select avg(x) from unnest(array[ct_pr(e.above200, ref.a_a200), ct_pr(e.off_hi, ref.a_hi), ct_pr(e.sma200_up, ref.a_up), ct_pr(e.run120, ref.a_run)]) x),
      g_react  = ct_pr(e.react_x, ref.a_rx)
    where e.qn = q;
    update ct_ev3 set score = (2 * coalesce(g_growth, 0.5) + coalesce(g_trend, 0.5) + coalesce(g_react, 0.5)) / 4 where qn = q;
    get diagnostics k = row_count; n := n + k;
  end loop;
  -- pr: score vs previous season's scores
  for q in select distinct qn from ct_ev3 where qn >= p_qn order by 1 loop
    update ct_ev3 e set pr = ct_pr(e.score, (select array_agg(score order by score) from ct_ev3 where qn = q - 1 and score is not null))
    where e.qn = q and (select count(*) from ct_ev3 where qn = q - 1 and score is not null) >= 200;
  end loop;
  update ct_ev3 e set tradeable = (e.mcap_pit >= 1000 and (e.turn20 is null or e.turn20 >= 5)),
     excl = nullif(concat_ws(', ', case when cl.guid = 'CUT' then 'guidance cut' end, case when r.bsh = 'STRESSED' then 'stressed balance sheet' end), '')
  from ct_res r left join ct_concall_lite cl on cl.isin = r.isin and cl.qn = r.qn
  where r.id = e.id and e.qn >= p_qn;
  return n;
end $$;

-- 3) model portfolio: process session p_i (execute yesterday's decisions at today's close, then decide for tomorrow)
create or replace function ct_model_step(p_i int) returns jsonb language plpgsql security definer set search_path = public as $$
declare d0 date := ct_day3(p_i); g numeric; eq numeric; r numeric := 0; nb int := 0; ns int := 0; cnt int; p record; c_ real; cap constant int := 15; cost constant numeric := 0.003;
  o record; free int; buys jsonb := '[]'; sells jsonb := '[]';
begin
  if d0 is null then return null; end if;
  select equity into eq from ct_model_day where i < p_i order by i desc limit 1; eq := coalesce(eq, 1);
  -- mark to market
  for p in select * from ct_model_pos where open loop
    c_ := ct_px3(p.isin, p_i);
    if c_ is not null and p.last_c > 0 then r := r + (c_ / p.last_c - 1) * p.w / cap; update ct_model_pos set last_c = c_ where ev_id = p.ev_id; end if;
  end loop;
  -- execute orders decided at the previous close
  select * into o from ct_model_orders where d = ct_day3(p_i - 1);
  if found then
    for p in select * from ct_model_pos where open and ev_id in (select x->>'ev' from jsonb_array_elements(coalesce(o.sells, '[]')) x) loop
      c_ := coalesce(ct_px3(p.isin, p_i), p.last_c);
      insert into ct_model_trade(isin, ev_id, entry_d, exit_d, entry_c, exit_c, w, ret, why, days)
      values (p.isin, p.ev_id, p.entry_d, d0, p.entry_c, c_, p.w, c_ / p.entry_c - 1 - 2 * cost, 'held 60 sessions', p_i - p.entry_i);
      update ct_model_pos set open = false, exit_d = d0 where ev_id = p.ev_id; ns := ns + 1;
    end loop;
    for p in select x from jsonb_array_elements(coalesce(o.buys, '[]')) x loop
      select count(*) into cnt from ct_model_pos where open;
      exit when cnt >= cap;
      c_ := ct_px3(p.x->>'isin', p_i);
      continue when c_ is null or c_ < 20 or exists (select 1 from ct_model_pos where open and isin = p.x->>'isin') or exists (select 1 from ct_model_pos where ev_id = p.x->>'ev');
      insert into ct_model_pos(isin, ev_id, entry_i, entry_d, entry_c, last_c, w, score, open)
      values (p.x->>'isin', p.x->>'ev', p_i, d0, c_, c_, (p.x->>'w')::numeric, (p.x->>'score')::numeric, true);
      nb := nb + 1;
    end loop;
  end if;
  r := r - (nb + ns) * cost / cap;
  eq := eq * (1 + r);
  -- decisions for tomorrow
  g := coalesce(ct_gauge(p_i), 0);
  select coalesce(jsonb_agg(jsonb_build_object('isin', isin, 'ev', ev_id) order by isin), '[]') into sells from ct_model_pos where open and p_i + 1 - entry_i >= 60;
  select count(*) into cnt from ct_model_pos where open and p_i + 1 - entry_i < 60;
  free := cap - cnt;
  if g > 0 and free > 0 then
    select coalesce(jsonb_agg(jsonb_build_object('isin', e.isin, 'ev', e.id, 'score', round(e.score, 4), 'w', round(g, 4)) order by e.score desc), '[]') into buys
    from (select * from (select distinct on (e.isin) e.* from ct_ev3 e
          where e.pr >= 0.9 and e.tradeable and e.excl is null and e.ei is not null and p_i + 1 between e.ei + 1 and e.ei + 10
            and not exists (select 1 from ct_model_pos mp where mp.open and mp.isin = e.isin and p_i + 1 - mp.entry_i < 60)
            and not exists (select 1 from ct_model_pos mp where mp.ev_id = e.id)
          order by e.isin, e.score desc) z order by z.score desc limit free) e;
  end if;
  insert into ct_model_orders(d, buys, sells, gauge) values (d0, buys, sells, g) on conflict (d) do update set buys = excluded.buys, sells = excluded.sells, gauge = excluded.gauge;
  select count(*) into cnt from ct_model_pos where open;
  insert into ct_model_day(d, i, r, equity, n, gauge, buys, sells) values (d0, p_i, r, eq, cnt, g, nb, ns)
  on conflict (d) do update set r = excluded.r, equity = excluded.equity, n = excluded.n, gauge = excluded.gauge, buys = excluded.buys, sells = excluded.sells;
  return jsonb_build_object('d', d0, 'r', round(r, 5), 'equity', round(eq, 4), 'n', cnt, 'gauge', round(g, 2), 'buys', nb, 'sells', ns);
end $$;

-- advance the model through every session not yet processed
create or replace function ct_model_advance(p_start date default '2025-04-01') returns jsonb language plpgsql security definer set search_path = public as $$
declare i0 int; i1 int; k int; last jsonb;
begin
  perform set_config('statement_timeout', '900s', true);
  select coalesce(max(i) + 1, (select min(i) from ct_days3 where d >= p_start)) into i0 from ct_model_day;
  select max(i) into i1 from ct_days3;
  for k in i0..i1 loop last := ct_model_step(k); end loop;
  return jsonb_build_object('from', ct_day3(i0), 'to', ct_day3(i1), 'last', last);
end $$;
