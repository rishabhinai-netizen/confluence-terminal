-- StockScans ids ('NSE:SYMBOL' / 'BSE:SCRIPID') -> ISIN, via BP symbols (ct_stock) and EquiSense symbols (ct_es_results).
create or replace function ct_map_ss() returns int language plpgsql security definer set search_path = public as $$
declare n int;
begin
  insert into ct_stock_map(ss_id, isin, how)
  select ids.ss_id, coalesce(s.isin, e.isin), case when s.isin is not null then 'bp_sym' else 'es_sym' end
  from (select distinct ss_id from ct_ss_scan union select distinct ss_id from ct_ss_concall where ss_id is not null) ids
  left join lateral (select isin from ct_stock where sym = split_part(ids.ss_id, ':', 2) limit 1) s on true
  left join lateral (select isin from ct_es_results where symbol = split_part(ids.ss_id, ':', 2) order by announced_at desc nulls last limit 1) e on true
  where coalesce(s.isin, e.isin) is not null
  on conflict (ss_id) do update set isin = excluded.isin, how = excluded.how, updated_at = now();
  get diagnostics n = row_count;
  return n;
end $$;
