-- Confluence Terminal v3: page JSON + nightly chain (13 Oct 2026). Depends on 100_v3_engine.sql.

-- prices are float4; let round(x, n) accept double precision
create or replace function public.round(double precision, integer) returns numeric language sql immutable parallel safe as $$ select round($1::numeric, $2) $$;

-- keep concall guidance in step with the raw EquiSense concall table
create or replace function ct_v3_sync_concalls() returns int language sql security definer set search_path = public as $$
  with x as (insert into ct_concall_lite(isin, qn, guid, tone)
    select distinct on (isin, fy * 4 + q) isin, fy * 4 + q, guidance_revision, tone from ct_es_concalls
    where isin like 'IN%' and q is not null and fy is not null order by isin, fy * 4 + q, concall_at desc nulls last
    on conflict (isin, qn) do update set guid = excluded.guid, tone = excluded.tone returning 1)
  select count(*)::int from x $$;

-- advance the model only through sessions whose inputs are complete:
--   prices: at least 80% as many rows as the session before;
--   breadth: that day's breadth is in, or it is past 08:30 IST the next calendar day (then the last known breadth is used)
create or replace function ct_model_ready() returns int language plpgsql stable set search_path = public as $$
declare k int; last_ok int; n0 int; n1 int; dk date;
begin
  select coalesce(max(i), 0) into last_ok from ct_model_day;
  if last_ok = 0 then return (select max(i) from ct_days3); end if;   -- first build: history is complete
  select count(*) into n0 from ct_prices where d = ct_day3(last_ok);
  for k in last_ok + 1 .. coalesce((select max(i) from ct_days3), 0) loop
    dk := ct_day3(k);
    select count(*) into n1 from ct_prices where d = dk;
    exit when n1 < 0.8 * n0;
    exit when not exists (select 1 from ct_breadth where d = dk) and now() < (dk + 1)::timestamp + interval '3 hours';
    last_ok := k; n0 := n1;
  end loop;
  return last_ok;
end $$;

create or replace function ct_model_advance(p_start date default '2025-01-01') returns jsonb language plpgsql security definer set search_path = public as $$
declare i0 int; i1 int; k int; last jsonb;
begin
  perform set_config('statement_timeout', '900s', true);
  select coalesce(max(i) + 1, (select min(i) from ct_days3 where d >= p_start)) into i0 from ct_model_day;
  i1 := ct_model_ready();
  if i1 is null or i1 < i0 then return jsonb_build_object('from', ct_day3(i0), 'note', 'nothing new'); end if;
  for k in i0..i1 loop last := ct_model_step(k); end loop;
  return jsonb_build_object('from', ct_day3(i0), 'to', ct_day3(i1), 'last', last);
end $$;

create or replace function ct_v3_page_data() returns jsonb language plpgsql security definer set search_path = public as $$
declare d0 date; i0 int; o record; m record; b record; out jsonb; live date := '2026-10-13';
begin
  select max(d), max(i) into d0, i0 from ct_model_day;
  select * into o from ct_model_orders where d = d0;
  select * into m from ct_mkt3 where d = d0;
  select * into b from ct_breadth where d <= d0 order by d desc limit 1;
  out := jsonb_build_object(
    'asof', d0, 'built_at', now(), 'live_from', live,
    'gauge', jsonb_build_object('v', round(o.gauge, 4),
       'votes', jsonb_build_array(
          jsonb_build_object('k', 'trend', 'on', m.idx > m.sma100, 'val', round((m.idx / m.sma100 - 1) * 100, 2)),
          jsonb_build_object('k', 'breadth', 'on', b.br50 > 50, 'val', b.br50),
          jsonb_build_object('k', 'highs', 'on', b.hi52 > b.lo52, 'hi', b.hi52, 'lo', b.lo52)),
       'hist', (select jsonb_agg(jsonb_build_array(d, round(gauge * 3)) order by d) from ct_model_day where d > d0 - 400)),
    'buys', (select coalesce(jsonb_agg(jsonb_build_object('isin', e.isin, 'sym', coalesce(s.sym, r.symbol), 'name', coalesce(s.name, r.name), 'sector', coalesce(s.sector, r.sector),
               'pub', e.pub_d, 'score', round(e.score, 3), 'pr', round(e.pr, 3), 'w', (x->>'w')::numeric,
               'gg', round(e.g_growth, 2), 'gt', round(e.g_trend, 2), 'gr', round(e.g_react, 2),
               'rev', round(e.rev_yoy, 1), 'pat', round(e.pat_yoy, 1), 'rx', round(e.react_x * 100, 1), 'off_hi', round(e.off_hi * 100, 1),
               'c', (select c from ct_prices p where p.isin = e.isin order by d desc limit 1), 'left', e.ei + 10 - i0) order by e.score desc), '[]')
             from jsonb_array_elements(coalesce(o.buys, '[]')) x join ct_ev3 e on e.id = x->>'ev' join ct_res r on r.id = e.id left join ct_stock s on s.isin = e.isin),
    'sells', (select coalesce(jsonb_agg(jsonb_build_object('isin', p.isin, 'sym', coalesce(s.sym, r.symbol), 'name', coalesce(s.name, r.name), 'entry_d', p.entry_d,
               'entry_c', p.entry_c, 'c', p.last_c, 'ret', round((p.last_c / p.entry_c - 1) * 100, 1)) order by p.entry_d), '[]')
             from jsonb_array_elements(coalesce(o.sells, '[]')) x join ct_model_pos p on p.ev_id = x->>'ev' join ct_res r on r.id = p.ev_id left join ct_stock s on s.isin = p.isin),
    'holdings', (select coalesce(jsonb_agg(jsonb_build_object('isin', p.isin, 'sym', coalesce(s.sym, r.symbol), 'name', coalesce(s.name, r.name), 'sector', coalesce(s.sector, r.sector),
               'entry_d', p.entry_d, 'entry_c', p.entry_c, 'c', p.last_c, 'ret', round((p.last_c / p.entry_c - 1) * 100, 1), 'w', round(p.w, 3),
               'held', i0 - p.entry_i, 'left', greatest(60 - (i0 + 1 - p.entry_i), 0), 'pub', e.pub_d,
               'rev', round(e.rev_yoy, 1), 'pat', round(e.pat_yoy, 1), 'score', round(e.score, 3)) order by p.entry_d, p.isin), '[]')
             from ct_model_pos p join ct_res r on r.id = p.ev_id left join ct_ev3 e on e.id = p.ev_id left join ct_stock s on s.isin = p.isin where p.open),
    -- every result still inside its 10-session buy window that clears the bar, and why it is (not) on the order list
    'window', (select coalesce(jsonb_agg(jsonb_build_object('isin', e.isin, 'sym', coalesce(s.sym, r.symbol), 'name', coalesce(s.name, r.name), 'sector', coalesce(s.sector, r.sector),
               'pub', e.pub_d, 'score', round(e.score, 3), 'pr', round(e.pr, 3), 'gg', round(e.g_growth, 2), 'gt', round(e.g_trend, 2), 'gr', round(e.g_react, 2),
               'rev', round(e.rev_yoy, 1), 'pat', round(e.pat_yoy, 1), 'rx', round(e.react_x * 100, 1), 'left', e.ei + 10 - i0,
               'status', case when e.excl is not null then 'excluded: ' || e.excl
                              when not coalesce(e.tradeable, false) then 'too small / illiquid'
                              when exists (select 1 from ct_model_pos mp where mp.open and mp.isin = e.isin) then 'held'
                              when exists (select 1 from jsonb_array_elements(coalesce(o.buys, '[]')) x where x->>'ev' = e.id) then 'buy'
                              when o.gauge = 0 then 'market gauge at zero'
                              else 'no free slot' end) order by e.score desc), '[]')
             from ct_ev3 e join ct_res r on r.id = e.id left join ct_stock s on s.isin = e.isin
             where e.pr >= 0.9 and i0 + 1 between e.ei + 1 and e.ei + 10),
    'season', (select jsonb_build_object('qn', max(qn), 'results', count(*) filter (where qn = (select max(qn) from ct_ev3 where pub_d >= d0 - 30)),
                 'qualified', count(*) filter (where qn = (select max(qn) from ct_ev3 where pub_d >= d0 - 30) and pr >= 0.9 and tradeable and excl is null)) from ct_ev3),
    'record', jsonb_build_object(
       'curve', (select jsonb_agg(jsonb_build_array(md.d, round(md.equity, 4), round(k.idx / (select idx from ct_mkt3 where i = (select min(i) from ct_model_day)), 4), md.n) order by md.d)
                 from ct_model_day md join ct_mkt3 k on k.d = md.d),
       'trades', (select jsonb_build_object('n', count(*), 'hit', round(avg((ret > 0)::int), 3), 'avg', round(avg(ret) * 100, 2), 'med', round((percentile_cont(0.5) within group (order by ret))::numeric * 100, 2),
                   'best', round(max(ret) * 100, 1), 'worst', round(min(ret) * 100, 1)) from ct_model_trade),
       'closed', (select coalesce(jsonb_agg(jsonb_build_object('sym', coalesce(s.sym, r.symbol), 'name', coalesce(s.name, r.name), 'entry_d', t.entry_d, 'exit_d', t.exit_d,
                   'ret', round(t.ret * 100, 1), 'w', round(t.w, 2)) order by t.exit_d desc, t.id desc), '[]')
                  from (select * from ct_model_trade order by exit_d desc, id desc limit 30) t join ct_res r on r.id = t.ev_id left join ct_stock s on s.isin = t.isin)),
    -- latest scored result per listed stock, for the lookup box
    'lookup', (select jsonb_agg(jsonb_build_array(z.isin, z.sym, z.name, z.sector, z.pub_d, round(z.score, 3), round(z.pr, 3), round(z.g_growth, 2), round(z.g_trend, 2), round(z.g_react, 2),
                 round(z.rev_yoy, 1), round(z.pat_yoy, 1), round(z.react_x * 100, 1), z.tradeable, z.excl, z.qn, z.ei + 10 - i0))
               from (select distinct on (e.isin) e.*, coalesce(s.sym, r.symbol) sym, coalesce(s.name, r.name) name, coalesce(s.sector, r.sector) sector
                     from ct_ev3 e join ct_res r on r.id = e.id left join ct_stock s on s.isin = e.isin
                     where e.score is not null and e.pub_d >= d0 - 200 order by e.isin, e.pub_d desc) z)
  );
  return out;
end $$;

create or replace function ct_v3_nightly() returns jsonb language plpgsql security definer set search_path = public as $$
declare log jsonb := '{}'; t timestamptz := clock_timestamp(); pd jsonb; q int;
begin
  perform set_config('statement_timeout', '900s', true);
  log := log || jsonb_build_object('concalls', ct_v3_sync_concalls());
  log := log || jsonb_build_object('market', ct_v3_market());
  select max(qn) - 1 into q from ct_res where ts > now() - interval '200 days';
  log := log || jsonb_build_object('features', ct_v3_features(q));
  log := log || jsonb_build_object('scored', ct_v3_score(q));
  log := log || jsonb_build_object('model', ct_model_advance());
  pd := ct_v3_page_data();
  insert into ct_page(id, html, built_at) values ('data', pd::text, now()) on conflict (id) do update set html = excluded.html, built_at = excluded.built_at;
  log := log || jsonb_build_object('bytes', length(pd::text), 'secs', round(extract(epoch from clock_timestamp() - t)));
  insert into ct_runs(kind, as_of, ok, note) values ('v3_nightly', (select max(d) from ct_model_day), true, log);
  return log;
exception when others then
  insert into ct_runs(kind, as_of, ok, note) values ('v3_nightly_fail', current_date, false, log || jsonb_build_object('error', sqlerrm));
  raise;
end $$;
