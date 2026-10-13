-- Confluence Terminal v4 page JSON (13 Oct 2026): Trend + Swing books (ct4_*) and Results Leaders (v3), equal thirds of capital.

-- current state of every universe stock (for the lookup box and for order details)
create or replace function ct4_state(p_i int) returns table(isin text, c real, rs numeric, univ boolean, h55 real, h10 real, sma50 numeric, ema10 numeric, hi250 real)
language sql stable set search_path = public as $$
  with today as (select p.isin, p.c from ct_prices p where p.d = ct_day3(p_i) and p.c > 0),
  px as (select p.isin, p.c, row_number() over (partition by p.isin order by p.d desc) k from ct_prices p
         where p.d > ct_day3(p_i - 250) and p.d <= ct_day3(p_i) and p.isin in (select isin from today)),
  agg as (select px.isin, max(px.c) filter (where k between 2 and 56) h55, max(px.c) filter (where k between 2 and 11) h10,
             avg(px.c) filter (where k <= 50) sma50, max(px.c) hi250, max(px.c) filter (where k = 127) c126,
             sum(px.c * power(1 - 2.0 / 11, k - 1)) filter (where k <= 60) / sum(power(1 - 2.0 / 11, k - 1)) filter (where k <= 60) ema10 from px group by px.isin),
  lastc as (select distinct on (p.isin) p.isin, p.c from ct_prices p where p.d > current_date - 30 order by p.isin, p.d desc),
  mc as (select distinct on (r.isin) r.isin, r.mcap_now from ct_res r where r.mcap_now is not null order by r.isin, r.qn desc, r.ts desc),
  u as (select t.isin, t.c, a.h55, a.h10, a.sma50, a.hi250, a.ema10, (t.c >= 20 and coalesce(mc.mcap_now * t.c / nullif(l.c, 0), 0) >= 1000) uu, t.c / nullif(a.c126, 0) - 1 r126
        from today t join agg a on a.isin = t.isin left join mc on mc.isin = t.isin left join lastc l on l.isin = t.isin)
  select u.isin, u.c, case when u.uu and u.r126 is not null then round((cume_dist() over (partition by (u.uu and u.r126 is not null) order by u.r126))::numeric, 4) end,
         u.uu, u.h55, u.h10, round(u.sma50, 2), round(u.ema10, 2), u.hi250 from u $$;

create or replace function ct4_page_data() returns jsonb language plpgsql security definer set search_path = public as $$
declare v3 jsonb; i0 int; d0 date; out jsonb; nm jsonb;
begin
  v3 := ct_v3_page_data();
  select max(i), max(d) into i0, d0 from ct4_day;
  -- names
  create temp table if not exists _nm (isin text primary key, sym text, name text, sector text) on commit drop;
  insert into _nm select distinct on (isin) isin, symbol, name, sector from ct_res where isin in (
      select isin from ct4_pos where open or exit_d > d0 - 120 union select isin from ct4_sig where i = i0) order by isin, qn desc, ts desc
  on conflict do nothing;
  create temp table if not exists _st on commit drop as select * from ct4_state(i0);
  out := jsonb_build_object(
    'asof', d0, 'built_at', now(), 'live_from', '2026-10-13',
    'gauge', v3->'gauge',
    'alloc', jsonb_build_object('trend', 1.0 / 3, 'swing', 1.0 / 3, 'results', 1.0 / 3),
    'books', jsonb_build_object(
      'trend', jsonb_build_object(
        'slots', 10,
        'hold', (select coalesce(jsonb_agg(jsonb_build_object('isin', p.isin, 'sym', n.sym, 'name', n.name, 'sector', n.sector, 'entry_d', p.entry_d, 'entry_c', p.entry_c,
                  'c', p.last_c, 'ret', round(((p.last_c / p.entry_c - 1) * 100)::numeric, 1), 'w', round(p.w, 3), 'held', i0 - p.entry_i,
                  'stop', s.sma50, 'risk', round(((1 - s.sma50 / nullif(p.last_c, 0)) * 100)::numeric, 1), 'armed', i0 + 1 - p.entry_i >= 3) order by p.entry_d), '[]')
                 from ct4_pos p left join _nm n on n.isin = p.isin left join _st s on s.isin = p.isin where p.book = 'trend' and p.open),
        'buys', (select coalesce(jsonb_agg(jsonb_build_object('isin', x->>'isin', 'sym', n.sym, 'name', n.name, 'sector', n.sector, 'rs', (x->>'rs')::numeric,
                  'c', (x->>'c')::numeric, 'h55', s.h55, 'stop', s.sma50, 'risk', round(((1 - s.sma50 / nullif((x->>'c')::numeric, 0)) * 100)::numeric, 1))), '[]')
                 from ct4_orders o, jsonb_array_elements(o.buys) x left join _nm n on n.isin = x->>'isin' left join _st s on s.isin = x->>'isin' where o.book = 'trend' and o.d = d0),
        'more', (select count(*) from ct4_sig where i = i0 and b55),
        'closed', (select coalesce(jsonb_agg(z order by z->>'exit_d' desc), '[]') from (select jsonb_build_object('sym', n.sym, 'name', n.name, 'entry_d', p.entry_d, 'exit_d', p.exit_d,
                  'ret', round(((p.exit_c / p.entry_c - 1 - 0.006) * 100)::numeric, 1), 'why', p.why) z from ct4_pos p left join _nm n on n.isin = p.isin
                  where p.book = 'trend' and not p.open order by p.exit_d desc limit 20) q),
        'stats', (select jsonb_build_object('n', count(*), 'hit', round(avg((exit_c / entry_c - 1 - 0.006 > 0)::int), 3), 'avg', round((avg(exit_c / entry_c - 1 - 0.006) * 100)::numeric, 2),
                  'days', round(avg(exit_i - entry_i), 1)) from ct4_pos where book = 'trend' and not open)),
      'swing', jsonb_build_object(
        'slots', 10,
        'hold', (select coalesce(jsonb_agg(jsonb_build_object('isin', p.isin, 'sym', n.sym, 'name', n.name, 'sector', n.sector, 'entry_d', p.entry_d, 'entry_c', p.entry_c,
                  'c', p.last_c, 'ret', round(((p.last_c / p.entry_c - 1) * 100)::numeric, 1), 'w', round(p.w, 3), 'held', i0 - p.entry_i, 'ema10', s.ema10,
                  'sell', p.xpend) order by p.entry_d), '[]')
                 from ct4_pos p left join _nm n on n.isin = p.isin left join _st s on s.isin = p.isin where p.book = 'swing' and p.open),
        'buys', (select coalesce(jsonb_agg(jsonb_build_object('isin', x->>'isin', 'sym', n.sym, 'name', n.name, 'sector', n.sector, 'rs', (x->>'rs')::numeric,
                  'c', (x->>'c')::numeric, 'h10', s.h10, 'ema10', s.ema10)), '[]')
                 from ct4_orders o, jsonb_array_elements(o.buys) x left join _nm n on n.isin = x->>'isin' left join _st s on s.isin = x->>'isin' where o.book = 'swing' and o.d = d0),
        'more', (select count(*) from ct4_sig where i = i0 and b10),
        'closed', (select coalesce(jsonb_agg(z order by z->>'exit_d' desc), '[]') from (select jsonb_build_object('sym', n.sym, 'name', n.name, 'entry_d', p.entry_d, 'exit_d', p.exit_d,
                  'ret', round(((p.exit_c / p.entry_c - 1 - 0.006) * 100)::numeric, 1), 'why', p.why) z from ct4_pos p left join _nm n on n.isin = p.isin
                  where p.book = 'swing' and not p.open order by p.exit_d desc limit 20) q),
        'stats', (select jsonb_build_object('n', count(*), 'hit', round(avg((exit_c / entry_c - 1 - 0.006 > 0)::int), 3), 'avg', round((avg(exit_c / entry_c - 1 - 0.006) * 100)::numeric, 2),
                  'days', round(avg(exit_i - entry_i), 1)) from ct4_pos where book = 'swing' and not open)),
      'results', jsonb_build_object('slots', 15, 'hold', v3->'holdings', 'buys', v3->'buys', 'sells', v3->'sells', 'window', v3->'window', 'season', v3->'season',
        'closed', v3->'record'->'closed', 'stats', v3->'record'->'trades')),
    -- combined record: equal thirds, rebalanced daily
    'curve', (select jsonb_agg(jsonb_build_array(z.d, round(z.eq, 4), round(z.t, 4), round(z.s, 4), round(z.rr, 4), round(z.mk, 4)) order by z.d) from (
        select d, exp(sum(ln(1 + (coalesce(rt, 0) + coalesce(rs_, 0) + coalesce(rr_, 0)) / 3)) over (order by d)) eq,
               exp(sum(ln(1 + coalesce(rt, 0))) over (order by d)) t, exp(sum(ln(1 + coalesce(rs_, 0))) over (order by d)) s,
               exp(sum(ln(1 + coalesce(rr_, 0))) over (order by d)) rr, mk
        from (select t.d, t.r rt, s.r rs_, m.r rr_, k.idx / (select idx from ct_mkt3 where d = (select min(d) from ct4_day)) mk
              from ct4_day t join ct4_day s on s.d = t.d and s.book = 'swing' left join ct_model_day m on m.d = t.d join ct_mkt3 k on k.d = t.d where t.book = 'trend') a) z),
    'lookup', (select jsonb_agg(jsonb_build_array(s.isin, n.sym, n.name, n.sector, s.c, s.rs, s.h55, s.h10, s.sma50, s.ema10, s.hi250,
                 (select jsonb_build_array(e.pub_d, round(e.pr, 3), e.qn) from ct_ev3 e where e.isin = s.isin and e.pr is not null order by e.pub_d desc limit 1),
                 (select string_agg(p.book, ',') from ct4_pos p where p.open and p.isin = s.isin)))
               from (select * from _st where univ) s join (select distinct on (isin) isin, symbol sym, name, sector from ct_res order by isin, qn desc, ts desc) n on n.isin = s.isin)
  );
  return out;
end $$;

create or replace function ct4_nightly() returns jsonb language plpgsql security definer set search_path = public as $$
declare log jsonb := '{}'; t timestamptz := clock_timestamp(); pd jsonb; q int;
begin
  perform set_config('statement_timeout', '1200s', true);
  log := log || jsonb_build_object('concalls', ct_v3_sync_concalls());
  log := log || jsonb_build_object('market', ct_v3_market());
  select max(qn) - 1 into q from ct_res where ts > now() - interval '200 days';
  log := log || jsonb_build_object('features', ct_v3_features(q), 'scored', ct_v3_score(q));
  log := log || jsonb_build_object('results_book', ct_model_advance());
  log := log || jsonb_build_object('books', ct4_advance());
  pd := ct4_page_data();
  insert into ct_page(id, html, built_at) values ('data', pd::text, now()) on conflict (id) do update set html = excluded.html, built_at = excluded.built_at;
  log := log || jsonb_build_object('bytes', length(pd::text), 'secs', round(extract(epoch from clock_timestamp() - t)));
  insert into ct_runs(kind, as_of, ok, note) values ('v4_nightly', (select max(d) from ct4_day), true, log);
  return log;
exception when others then
  insert into ct_runs(kind, as_of, ok, note) values ('v4_nightly_fail', current_date, false, log || jsonb_build_object('error', sqlerrm));
  raise;
end $$;
