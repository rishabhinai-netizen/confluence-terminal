-- Nightly chain + on-demand stock dossier + search (12 Oct 2026).
insert into ct_secret(k, v, note) values ('page_key', md5(random()::text || clock_timestamp()::text) || md5(random()::text), 'header x-ct-key between the Cloudflare worker and ct-page')
on conflict (k) do nothing;

-- full dossier for one stock: card + every result/concall/smart-money event we hold, with what happened afterwards
create or replace function ct_card_full(p_isin text) returns jsonb language sql stable security definer set search_path = public as $$
  select ct_card(p_isin) || jsonb_build_object(
    'hist', (select coalesce(jsonb_agg(jsonb_build_object('kind', e.kind, 'd', e.pub_d, 'a', e.a, 'rules', e.rules, 'react', round(e.react * 100, 1),
               'x20', round(e.x20 * 100, 1), 'x60', round(e.x60 * 100, 1), 'valid', e.valid) order by e.pub_d desc), '[]')
             from (select * from ct_ev where isin = p_isin and (kind <> 'smart' or rules <> '{}') order by pub_d desc limit 40) e),
    'px', (select jsonb_agg(jsonb_build_array(d, c) order by d) from ct_prices where isin = p_isin and d >= current_date - 400),
    'filings', (select coalesce(jsonb_agg(jsonb_build_object('kind', kind, 'at', filed_at, 'impact', impact, 'dir', direction, 'head', raw->>'headline') order by filed_at desc), '[]')
                from (select * from ct_es_filings where isin = p_isin order by filed_at desc limit 12) f))
$$;

create or replace function ct_search(p_q text) returns jsonb language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object('isin', isin, 'sym', sym, 'name', name) order by rk, sym), '[]') from (
    select isin, sym, name, case when upper(sym) = upper(p_q) then 0 when sym ilike p_q || '%' then 1 else 2 end rk
    from ct_stock where (sym ilike p_q || '%' or name ilike '%' || p_q || '%') and exists (select 1 from ct_prices p where p.isin = ct_stock.isin)
    order by rk, sym limit 20) z
$$;

-- the whole nightly chain; each step logged. Safe to run any number of times.
create or replace function ct_nightly() returns jsonb language plpgsql security definer set search_path = public as $$
declare log jsonb := '{}'; t timestamptz := clock_timestamp(); pd jsonb;
begin
  perform set_config('statement_timeout', '900s', true);
  log := log || jsonb_build_object('market', ct_refresh_market());
  log := log || jsonb_build_object('events', ct_build_events(current_date - 200));
  log := log || jsonb_build_object('late', ct_flag_late());
  log := log || jsonb_build_object('stats', ct_refresh_stats());
  log := log || jsonb_build_object('picks_logged', ct_log_picks());
  pd := ct_page_data();
  insert into ct_page(id, html, built_at) values ('data', pd::text, now()) on conflict (id) do update set html = excluded.html, built_at = excluded.built_at;
  log := log || jsonb_build_object('bytes', length(pd::text), 'drift', jsonb_array_length(pd->'drift'), 'secs', extract(epoch from clock_timestamp() - t));
  insert into ct_runs(kind, as_of, ok, note) values ('nightly', (select max(d) from ct_days), true, log);
  return log;
exception when others then
  insert into ct_runs(kind, as_of, ok, note) values ('nightly_fail', current_date, false, log || jsonb_build_object('error', sqlerrm));
  raise;
end $$;
