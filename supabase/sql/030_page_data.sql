-- Page data for Confluence Terminal v2. One JSON document, rebuilt nightly by ct-build and served to the page.
-- Everything shown on the page comes from here; every number traces to a source table.

create table if not exists ct_pick_log (d date not null, isin text not null, board text not null, rank int, entry_d date, entry_c real,
  react numeric, why jsonb, primary key (d, isin, board));
alter table ct_pick_log enable row level security;

create or replace function ct_try_jsonb(t text) returns jsonb language plpgsql immutable as $$
begin return t::jsonb; exception when others then return null; end $$;

-- one card per stock: latest result + concall (EquiSense), StockScans concall score, scans, recent flags/smart money
create or replace function ct_card(p_isin text) returns jsonb language sql stable security definer set search_path = public as $$
  with st as (select * from ct_stock where isin = p_isin),
  r as (select * from ct_latest_result(p_isin) limit 1),
  rp as (select raw from ct_latest_result(p_isin) offset 1 limit 1),
  c as (select * from ct_es_concalls where isin = p_isin order by fy desc, q desc, concall_at desc nulls last limit 1),
  ssid as (select ss_id from ct_stock_map where isin = p_isin),
  sc as (select * from ct_ss_concall where ss_id in (select ss_id from ssid) order by concall_at desc nulls last limit 1),
  sd as (select max(d) d from ct_ss_scan),
  scans as (select coalesce(jsonb_agg(distinct coalesce(df.name, s.scan_id)), '[]') j from ct_ss_scan s left join ct_ss_scan_def df using (scan_id)
            where s.d = (select d from sd) and s.ss_id in (select ss_id from ssid)),
  fl as (select coalesce(jsonb_agg(jsonb_build_object('rule', rl, 'd', e.pub_d, 'kind', e.kind, 'a', e.a) order by e.pub_d desc), '[]') j
         from ct_ev e, unnest(e.rules) rl where e.isin = p_isin and e.pub_d >= current_date - 120
           and rl in ('avoid_miss_fall','avoid_stressed','avoid_guidance_cut','guidance_missed','flag_bulk_churn','flag_insider_sell','in_play_bulk','guidance_raised','promoter_buy','drift_buy')),
  px as (select c last_c, d last_d from ct_prices where isin = p_isin order by d desc limit 1),
  hi as (select max(h) hi52 from ct_prices where isin = p_isin and d >= current_date - 365)
  select jsonb_strip_nulls(jsonb_build_object(
    'isin', p_isin, 'sym', coalesce((select sym from st), (select symbol from r)), 'name', coalesce((select raw->>'companyName' from r), (select name from st)),
    'sector', (select raw->>'companySector' from r), 'grp', (select grp from st), 'mcap', (select (raw->>'marketCap')::numeric from r), 'pe', (select (raw->>'pe')::numeric from r),
    'ecs_now', (select (raw->>'ecsScore')::numeric from r),
    'last_c', (select last_c from px), 'last_d', (select last_d from px), 'off_hi', (select round(((last_c / nullif(hi52,0)) - 1)::numeric * 100, 1) from px, hi),
    'res', (select jsonb_build_object('q', 'Q' || q || ' FY' || right(fy::text, 2), 'at', announced_at, 'verdict', verdict, 'pead', pead_label, 'bsh', bsh,
              'rev', (raw->>'revenue')::numeric, 'pat', (raw->>'profitAfterTax')::numeric, 'rev_yoy', (raw->>'revenueYoyGrowth')::numeric,
              'pat_yoy', (raw->>'patYoyGrowth')::numeric, 'opm', (raw->>'opm')::numeric, 'opm_bps', (raw->>'opmYoyBps')::numeric,
              'eps_yoy', (raw->>'epsYoyGrowth')::numeric, 'why', raw->>'resultVerdictReason', 'pdf', raw->>'pdfUrl',
              'ins', (select jsonb_agg(x) from (select jsonb_build_object('t', i->>'insight', 's', i->>'sentiment') x
                        from jsonb_array_elements(coalesce(case when jsonb_typeof(raw->'insightsJson') = 'string' then ct_try_jsonb(raw->>'insightsJson')
                                                   when jsonb_typeof(raw->'insightsJson') = 'array' then raw->'insightsJson' end, '[]'::jsonb)) i limit 5) z))
            from r),
    'prev_res', (select jsonb_build_object('rev_yoy', (raw->>'revenueYoyGrowth')::numeric, 'pat_yoy', (raw->>'patYoyGrowth')::numeric, 'q', 'Q' || (raw->>'quarter') || ' FY' || right(raw->>'fy', 2)) from rp),
    'cc', (select jsonb_build_object('q', 'Q' || q || ' FY' || right(fy::text, 2), 'at', concall_at, 'guid', guidance_revision, 'deliv', guidance_delivery, 'tone', tone,
              'candor', candor, 'eq', earnings_quality, 'analyst', analyst_sentiment, 'story', story_type, 'summary', left(raw->>'shortSummaryText', 700),
              'guidance', left(raw->>'managementGuidance', 600), 'tags', raw->>'tags', 'audio', raw->>'recordingLink') from c),
    'ss', (select jsonb_build_object('score', result_score, 'sent', sentiment_tier, 'tags', tags, 'congrats', congrats, 'at', concall_at, 'q', quarter) from sc),
    'scans', (select j from scans), 'flags', (select j from fl)))
$$;

create or replace function ct_page_data() returns jsonb language plpgsql security definer set search_path = public as $$
declare mx int; lastd date; mk record; out jsonb; cq int; cfy int; stamp timestamptz;
begin
  select max(i), max(d) into mx, lastd from ct_days;
  select * into mk from ct_mkt where d = lastd;
  select max(computed_at) into stamp from ct_signal_stats;
  select q, fy into cq, cfy from ct_es_results where announced_at is not null order by fy desc, q desc limit 1;
  with drift as (
    select e.*, s.sector from ct_ev e
    left join lateral (select raw->>'companySector' sector from ct_es_results where id = e.id) s on true
    where e.kind = 'result' and 'drift_buy' = any(e.rules) and e.entry_i >= mx - 9),
  ranked as (select d.*, row_number() over (partition by coalesce(sector, '?') order by react desc) sec_rank from drift d),
  board as (select r.*, row_number() over (order by (sec_rank <= 2) desc, react desc) pos from ranked r)
  select jsonb_build_object(
    'meta', jsonb_build_object('built_at', now(), 'as_of', lastd, 'mx', mx,
       'mkt', jsonb_build_object('up', mk.up, 'idx', round(mk.idx, 4), 'sma50', round(mk.sma50, 4), 'vs_sma', round((mk.idx / mk.sma50 - 1) * 100, 2),
               'r1d', round(mk.r * 100, 2), 'r20', (select round((mk.idx / idx - 1) * 100, 2) from ct_mkt where i = mx - 20),
               'path', (select jsonb_agg(jsonb_build_array(d, round(idx, 4), round(sma50, 4)) order by d) from ct_mkt where i > mx - 130),
               'bp_breadth', (select jsonb_build_object('d', d, 'pct', breadth, 'chg20', breadth_chg20) from ct_market order by d desc limit 1)),
       'fresh', jsonb_build_object(
          'prices', lastd,
          'es_run', (select max(run_at) from ct_runs where kind = 'es' and ok),
          'es_last_result', (select max(announced_at) from ct_es_results),
          'ss_run', (select max(run_at) from ct_runs where kind = 'ss' and ok),
          'ss_snap', (select max(d) from ct_ss_scan),
          'ss_cookie_note', (select note from ct_secret where k = 'stockscans_cookie'),
          'stats_at', stamp),
       'season', jsonb_build_object('q', cq, 'fy', cfy,
          'n', (select count(*) from ct_es_results where q = cq and fy = cfy),
          'beat', (select count(*) from ct_es_results where q = cq and fy = cfy and verdict = 'BEAT'),
          'miss', (select count(*) from ct_es_results where q = cq and fy = cfy and verdict = 'MISS'),
          'inline', (select count(*) from ct_es_results where q = cq and fy = cfy and verdict = 'IN_LINE'),
          'drift', (select count(*) from ct_ev e join ct_es_results r on r.id = e.id where e.kind = 'result' and r.q = cq and r.fy = cfy and 'drift_buy' = any(e.rules)))),
    'evidence', (select jsonb_agg(jsonb_build_object('s', signal, 'f', family, 'h', horizon, 'p', period, 'n', n, 'hit', hit, 'med', med_excess, 'mean', mean_excess, 'p25', p25, 'p75', p75))
                 from ct_signal_stats where computed_at = stamp),
    'drift', (select coalesce(jsonb_agg(ct_card(b.isin) || jsonb_build_object('pos', b.pos, 'sec_rank', b.sec_rank, 'entry_d', b.entry_d, 'entry_c', b.entry_c,
                 'react', round(b.react * 100, 1), 'age', mx - b.entry_i, 'since', round(((select c from ct_prices where isin = b.isin order by d desc limit 1) / b.entry_c - 1)::numeric * 100, 1),
                 'ev_q', b.a->>'q') order by b.pos), '[]') from board b),
    'pending', (select coalesce(jsonb_agg(jsonb_build_object('isin', e.isin, 'sym', r.symbol, 'name', r.raw->>'companyName', 'sector', r.raw->>'companySector',
                 'at', r.announced_at, 'pat_yoy', (e.a->>'pat')::numeric, 'rev_yoy', (e.a->>'rev')::numeric, 'verdict', e.a->>'verdict',
                 'last_c', (select c from ct_prices where isin = e.isin order by d desc limit 1)) order by r.announced_at desc), '[]')
                from ct_ev e join ct_es_results r on r.id = e.id
                where e.kind = 'result' and e.valid and e.entry_i is null and (e.a->>'pat')::numeric >= 25 and (e.a->>'rev')::numeric >= 15
                  and exists (select 1 from ct_prices p where p.isin = e.isin)),
    'avoid', (select coalesce(jsonb_agg(z.j order by z.d desc), '[]') from (
                select distinct on (e.isin, rl) e.pub_d d, jsonb_build_object('isin', e.isin, 'sym', coalesce(st.sym, r.symbol), 'name', coalesce(r.raw->>'companyName', st.name), 'd', e.pub_d,
                   'rule', rl, 'kind', e.kind, 'a', e.a, 'react', round(e.react * 100, 1),
                   'n', (select count(*) from ct_ev e3 where e3.isin = e.isin and rl = any(e3.rules) and e3.entry_i >= mx - 14),
                   'since', round(((select c from ct_prices where isin = e.isin order by d desc limit 1) / nullif(e.entry_c, 0) - 1)::numeric * 100, 1)) j
                from ct_ev e cross join unnest(e.rules) rl left join ct_stock st on st.isin = e.isin
                left join lateral (select symbol, raw from ct_latest_result(e.isin) limit 1) r on true
                where e.entry_i >= mx - 14 and rl in ('avoid_miss_fall','avoid_stressed','avoid_guidance_cut','guidance_missed','flag_bulk_churn','flag_insider_sell')
                  and exists (select 1 from ct_prices p where p.isin = e.isin)
                order by e.isin, rl, e.pub_d desc) z),
    'in_play', (select coalesce(jsonb_agg(z.j order by z.pct desc), '[]') from (
                select g.isin, g.pct, jsonb_build_object('isin', g.isin, 'sym', coalesce(st.sym, (select symbol from ct_es_smart where isin = g.isin limit 1)), 'name', st.name,
                   'd', g.last_d, 'n', g.n, 'pct', g.pct, 'cr', g.cr, 'sides', g.sides, 'who', g.who,
                   'since', round(((select c from ct_prices where isin = g.isin order by d desc limit 1) / nullif(g.entry_c, 0) - 1)::numeric * 100, 1),
                   'res', (select jsonb_build_object('q', 'Q' || q || ' FY' || right(fy::text, 2), 'pat_yoy', (raw->>'patYoyGrowth')::numeric, 'rev_yoy', (raw->>'revenueYoyGrowth')::numeric, 'verdict', verdict)
                           from ct_latest_result(g.isin) limit 1)) j
                from (select isin, max(pub_d) last_d, count(*) n, round(sum((a->>'pct_mcap')::numeric), 2) pct, round(sum((a->>'cr')::numeric), 1) cr,
                             array_agg(distinct a->>'side') sides, (array_agg(a->>'who' order by (a->>'cr')::numeric desc))[1] who, (array_agg(entry_c order by entry_i))[1] entry_c
                      from ct_ev where kind = 'smart' and 'in_play_bulk' = any(rules) and entry_i >= mx - 9 and exists (select 1 from ct_prices p where p.isin = ct_ev.isin)
                      group by isin) g
                left join ct_stock st on st.isin = g.isin order by g.pct desc limit 60) z),
    'catalysts', (select coalesce(jsonb_agg(z.j order by z.at desc), '[]') from (
                select f.filed_at at, jsonb_build_object('isin', f.isin, 'sym', f.symbol, 'name', f.raw->>'companyName', 'kind', f.kind, 'at', f.filed_at, 'impact', f.impact,
                   'dir', f.direction, 'head', f.raw->>'headline', 'why', left(f.raw->>'reason', 400), 'mcap', (f.raw->>'marketCap')::numeric, 'pdf', f.raw->>'pdfUrl') j
                from ct_es_filings f where f.filed_at >= now() - interval '7 days' and f.impact >= 60 and f.direction = 'POSITIVE' order by f.impact desc limit 40) z),
    'sectors', (select jsonb_build_object('d', max(d), 'industry', (select jsonb_agg(jsonb_build_object('k', name, 'p', parent, 's', score, 'st', status, 'n', (raw->>'totalCompanies')::int) order by score desc)
                    from ct_ss_market where kind = 'industry' and d = (select max(d) from ct_ss_market where kind = 'industry')),
                  'index', (select jsonb_agg(jsonb_build_object('k', name, 's', score, 'st', status) order by score desc)
                    from ct_ss_market where kind = 'index' and d = (select max(d) from ct_ss_market where kind = 'index')))
                from ct_ss_market),
    'calendar', (select body from ct_snapshot where k = 'ss_calendar' order by d desc limit 1),
    'ss_breadth', (select body from ct_snapshot where k = 'ss_breadth' order by d desc limit 1),
    'track', (select coalesce(jsonb_agg(jsonb_build_object('d', p.d, 'isin', p.isin, 'sym', st.sym, 'rank', p.rank, 'entry_d', p.entry_d, 'entry_c', p.entry_c,
                 'last_c', (select c from ct_prices where isin = p.isin order by d desc limit 1),
                 'mkt', (select m2.idx / m1.idx - 1 from ct_mkt m1, ct_mkt m2 where m1.d = p.entry_d and m2.d = lastd)) order by p.d desc, p.rank), '[]')
              from (select distinct on (isin) * from ct_pick_log where board = 'drift' order by isin, d) p left join ct_stock st on st.isin = p.isin),
    'lookup', (select jsonb_agg(jsonb_build_array(l.isin, l.sym, l.name, l.sector, l.q, l.pat, l.rev, l.verdict, round(l.react * 100, 1), l.rules, l.at))
               from (select distinct on (e.isin) e.isin, coalesce(st.sym, r.symbol) sym, coalesce(r.raw->>'companyName', st.name) name, r.raw->>'companySector' sector,
                        e.a->>'q' q, (e.a->>'pat')::numeric pat, (e.a->>'rev')::numeric rev, e.a->>'verdict' verdict, e.react,
                        (select array_agg(distinct rl) from ct_ev e2, unnest(e2.rules) rl where e2.isin = e.isin and e2.pub_d >= current_date - 120) rules, e.pub_d at
                     from ct_ev e join ct_es_results r on r.id = e.id left join ct_stock st on st.isin = e.isin
                     where e.kind = 'result' and e.entry_c is not null and e.valid order by e.isin, r.fy desc, r.q desc, e.pub_d desc) l)
  ) into out;
  return out;
end $$;

-- record today's board (first sighting of each stock is what the track record measures)
create or replace function ct_log_picks() returns int language plpgsql security definer set search_path = public as $$
declare mx int; lastd date; n int;
begin
  select max(i), max(d) into mx, lastd from ct_days;
  insert into ct_pick_log(d, isin, board, rank, entry_d, entry_c, react, why)
  select lastd, b.isin, 'drift', b.pos, b.entry_d, b.entry_c, b.react, jsonb_build_object('pat', b.a->>'pat', 'rev', b.a->>'rev', 'q', b.a->>'q', 'mkt_up', b.up)
  from (select e.*, row_number() over (order by react desc) pos from ct_ev e where e.kind = 'result' and 'drift_buy' = any(e.rules) and e.entry_i >= mx - 9) b
  on conflict (d, isin, board) do nothing;
  get diagnostics n = row_count;
  return n;
end $$;
