-- Confluence Terminal v4 (13 Oct 2026): two any-day books next to Results Leaders (v3).
-- Research: research/README.md (v4) and research/v4/*.py (Python reference: swing.py simulate()).
--   Trend : buy at the next close after a close above the highest close of the previous 55 sessions; strongest 6-month
--           relative strength first; 10 slots; size = market gauge. Exit: stop order at the previous session's 50-day
--           average (filled at that level, or at the open if it gaps below), active from the 3rd session.
--   Swing : buy at the next close after a close above the previous 10-session high; strongest relative strength first;
--           10 slots; size = market gauge. Exit: at the next close after a close below the 10-day EMA (from the 2nd
--           session), or after 30 sessions.
--   Universe: close >= 20, >= 200 sessions listed, market cap >= Rs 1,000 cr (point in time), 20-day median turnover
--             >= Rs 5 cr where volume is known. Costs 0.3% per side.

create table if not exists ct4_first (isin text primary key, i_first int);
create table if not exists ct4_sig (i int not null, d date not null, isin text not null, c real, rs numeric, b55 boolean, b10 boolean, primary key (i, isin));
create table if not exists ct4_pos (book text not null, isin text not null, entry_i int not null, entry_d date, entry_c real, last_c real, w numeric,
  rs numeric, open boolean default true, xpend text, exit_i int, exit_d date, exit_c real, why text, primary key (book, isin, entry_i));
create index if not exists ct4_pos_open on ct4_pos(book, open);
create table if not exists ct4_day (book text not null, d date not null, i int, r numeric, equity numeric, n int, expo numeric, primary key (book, d));
create table if not exists ct4_orders (book text not null, d date not null, buys jsonb, sells jsonb, gauge numeric, primary key (book, d));
alter table ct4_first enable row level security; alter table ct4_sig enable row level security; alter table ct4_pos enable row level security;
alter table ct4_day enable row level security; alter table ct4_orders enable row level security;

-- first session each stock has a price (ct_prices starts Jan 2024; older listings count from there)
create or replace function ct4_refresh_first() returns int language sql security definer set search_path = public as $$
  with x as (insert into ct4_first(isin, i_first)
    select p.isin, min(dd.i) from ct_prices p join ct_days3 dd on dd.d = p.d group by p.isin
    on conflict (isin) do update set i_first = excluded.i_first returning 1) select count(*)::int from x $$;

-- candidates (breakouts) for session p_i with their relative-strength percentile inside the universe
create or replace function ct4_signals(p_i int) returns int language plpgsql security definer set search_path = public as $$
declare d0 date := ct_day3(p_i); n int;
begin
  if d0 is null then return 0; end if;
  insert into ct4_sig(i, d, isin, c, rs, b55, b10)
  with today as (select isin, c from ct_prices where d = d0 and c > 0),
  lastc as (select distinct on (isin) isin, c from ct_prices where d > current_date - 30 order by isin, d desc),
  mc as (select distinct on (isin) isin, mcap_now from ct_res where mcap_now is not null order by isin, qn desc, ts desc),
  w as (select p.isin, max(p.c) filter (where p.d >= ct_day3(p_i - 10)) h10, max(p.c) h55
        from ct_prices p where p.d >= ct_day3(p_i - 55) and p.d < d0 group by p.isin),
  tv as (select p.isin, percentile_cont(0.5) within group (order by p.c::numeric * p.v / 1e7) t20
         from ct_prices p where p.d > ct_day3(p_i - 20) and p.d <= d0 and p.v is not null group by p.isin),
  old as (select isin, c from ct_prices where d = ct_day3(p_i - 126)),
  u as (select t.isin, t.c, w.h10, w.h55, t.c / nullif(o.c, 0) - 1 r126
        from today t join ct4_first f on f.isin = t.isin join mc on mc.isin = t.isin join lastc l on l.isin = t.isin
        left join w on w.isin = t.isin left join tv on tv.isin = t.isin left join old o on o.isin = t.isin
        where t.c >= 20 and p_i - f.i_first + 1 >= 200 and mc.mcap_now * t.c / nullif(l.c, 0) >= 1000 and (tv.t20 is null or tv.t20 >= 5)),
  r as (select u.*, cume_dist() over (order by r126) rs from u where r126 is not null)
  select p_i, d0, isin, c, round(rs::numeric, 4), c > h55, c > h10 from r where c > h10 or c > h55
  on conflict (i, isin) do update set c = excluded.c, rs = excluded.rs, b55 = excluded.b55, b10 = excluded.b10;
  get diagnostics n = row_count; return n;
end $$;

create or replace function ct4_sma(p_isin text, p_i int, p_n int) returns numeric language sql stable set search_path = public as $$
  select case when count(*) >= p_n * 0.9 then avg(c) end from ct_prices where isin = p_isin and d > ct_day3(p_i - p_n) and d <= ct_day3(p_i) $$;
-- EMA(n) as an exponentially weighted average of the last 6n closes (converges to the recursive EMA)
create or replace function ct4_ema(p_isin text, p_i int, p_n int) returns numeric language sql stable set search_path = public as $$
  with x as (select c, row_number() over (order by d desc) - 1 k from ct_prices where isin = p_isin and d > ct_day3(p_i - 6 * p_n) and d <= ct_day3(p_i))
  select case when count(*) >= p_n then sum(c * power(1 - 2.0 / (p_n + 1), k)) / sum(power(1 - 2.0 / (p_n + 1), k)) end from x $$;

-- one session of one book: manage exits at today's prices, buy yesterday's candidates at today's close, decide tomorrow's exits
create or replace function ct4_step(p_book text, p_i int) returns jsonb language plpgsql security definer set search_path = public as $$
declare d0 date := ct_day3(p_i); slots constant int := 10; cost constant numeric := 0.003; g numeric; eq numeric; r numeric := 0; ntr numeric := 0;
  p record; px record; lvl numeric; xp numeric; v_why text; cnt int; nb int := 0; ns int := 0; buys jsonb := '[]'; sells jsonb := '[]'; ex numeric;
begin
  if d0 is null then return null; end if;
  select equity into eq from ct4_day where book = p_book and i < p_i order by i desc limit 1; eq := coalesce(eq, 1);
  for p in select * from ct4_pos where book = p_book and open loop
    select o, l, c into px from ct_prices where isin = p.isin and d = d0;
    if px.c is null then continue; end if;
    xp := null; v_why := null;
    if p.xpend is not null then xp := px.c; v_why := p.xpend;
    elsif p_book = 'trend' and p_i - p.entry_i >= 3 then
      lvl := ct4_sma(p.isin, p_i - 1, 50);
      if lvl is not null and coalesce(px.l, px.c) <= lvl then xp := case when px.o is not null then least(lvl, px.o) else lvl * 0.995 end; v_why := 'stop at 50-day average'; end if;
    end if;
    if xp is null and p_book = 'trend' and p_i - p.entry_i >= 250 then xp := px.c; v_why := 'max hold'; end if;
    if xp is not null then
      r := r + (xp / p.last_c - 1) * p.w / slots; ntr := ntr + p.w; ns := ns + 1;
      update ct4_pos set open = false, exit_i = p_i, exit_d = d0, exit_c = xp, why = v_why, last_c = xp where book = p.book and isin = p.isin and entry_i = p.entry_i;
    else
      r := r + (px.c / p.last_c - 1) * p.w / slots;
      update ct4_pos set last_c = px.c where book = p.book and isin = p.isin and entry_i = p.entry_i;
    end if;
  end loop;
  -- buys: yesterday's candidates, strongest first, at today's close; size = gauge known at yesterday's close
  g := coalesce(ct_gauge(p_i - 1), 0);
  if g > 0 then
    for p in select s.isin, s.rs, t.c from ct4_sig s join ct_prices t on t.isin = s.isin and t.d = d0
             where s.i = p_i - 1 and (case when p_book = 'trend' then s.b55 else s.b10 end) order by s.rs desc, s.isin loop
      select count(*) into cnt from ct4_pos where book = p_book and open;
      exit when cnt >= slots;
      continue when exists (select 1 from ct4_pos where book = p_book and open and isin = p.isin) or p.c is null or p.c <= 0;
      insert into ct4_pos(book, isin, entry_i, entry_d, entry_c, last_c, w, rs, open) values (p_book, p.isin, p_i, d0, p.c, p.c, g, p.rs, true)
      on conflict (book, isin, entry_i) do nothing;
      ntr := ntr + g; nb := nb + 1;
    end loop;
  end if;
  r := r - ntr * cost / slots; eq := eq * (1 + r);
  -- swing exits are decided at the close and executed at the next close
  if p_book = 'swing' then
    for p in select * from ct4_pos where book = 'swing' and open and xpend is null and p_i - entry_i >= 2 loop
      ex := ct4_ema(p.isin, p_i, 10);
      if (ex is not null and p.last_c < ex) or p_i - p.entry_i >= 30 then
        update ct4_pos set xpend = case when p_i - p.entry_i >= 30 then '30 sessions' else 'close below 10-day EMA' end where book = 'swing' and isin = p.isin and entry_i = p.entry_i;
      end if;
    end loop;
  end if;
  -- orders shown for tomorrow: pending swing exits; trend stop levels; candidates for tomorrow's buys
  select coalesce(jsonb_agg(jsonb_build_object('isin', isin, 'why', xpend)), '[]') into sells from ct4_pos where book = p_book and open and xpend is not null;
  select count(*) into cnt from ct4_pos where book = p_book and open and xpend is null;
  select coalesce(jsonb_agg(jsonb_build_object('isin', isin, 'rs', rs, 'c', c) order by rs desc), '[]') into buys from (
    select s.isin, s.rs, s.c from ct4_sig s where s.i = p_i and (case when p_book = 'trend' then s.b55 else s.b10 end)
      and not exists (select 1 from ct4_pos q where q.book = p_book and q.open and q.isin = s.isin and q.xpend is null)
    order by s.rs desc limit greatest(slots - cnt, 0)) z;
  insert into ct4_orders(book, d, buys, sells, gauge) values (p_book, d0, case when coalesce(ct_gauge(p_i), 0) > 0 then buys else '[]' end, sells, ct_gauge(p_i))
  on conflict (book, d) do update set buys = excluded.buys, sells = excluded.sells, gauge = excluded.gauge;
  select count(*) into cnt from ct4_pos where book = p_book and open;
  insert into ct4_day(book, d, i, r, equity, n, expo) values (p_book, d0, p_i, r, eq, cnt, (select coalesce(sum(w), 0) / slots from ct4_pos where book = p_book and open))
  on conflict (book, d) do update set r = excluded.r, equity = excluded.equity, n = excluded.n, expo = excluded.expo;
  return jsonb_build_object('book', p_book, 'd', d0, 'r', round(r, 5), 'eq', round(eq, 4), 'n', cnt, 'buys', nb, 'sells', ns);
end $$;

-- advance both books through every complete session not yet processed (same readiness rule as the v3 model)
create or replace function ct4_advance(p_start date default '2025-01-01') returns jsonb language plpgsql security definer set search_path = public as $$
declare i0 int; i1 int; k int; b text; last jsonb := '{}';
begin
  perform set_config('statement_timeout', '1200s', true);
  perform ct4_refresh_first();
  i1 := ct_model_ready();
  foreach b in array array['trend', 'swing'] loop
    select coalesce(max(i) + 1, (select min(i) from ct_days3 where d >= p_start)) into i0 from ct4_day where book = b;
    if i1 is null or i1 < i0 then continue; end if;
    for k in i0..i1 loop
      if not exists (select 1 from ct4_sig where i = k - 1) then perform ct4_signals(k - 1); end if;
      if not exists (select 1 from ct4_sig where i = k) then perform ct4_signals(k); end if;
      last := last || jsonb_build_object(b, ct4_step(b, k));
    end loop;
  end loop;
  return jsonb_build_object('to', ct_day3(i1), 'last', last);
end $$;
