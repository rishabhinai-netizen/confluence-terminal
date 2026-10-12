-- Schedules (pg_cron + pg_net). Times are UTC; IST = UTC + 5:30. ct_call() reads the anon key from ct_secret('ct_anon_key').
create extension if not exists pg_cron; create extension if not exists pg_net;
create or replace function ct_call(p_fn text, p_qs text default '') returns bigint language sql security definer set search_path = public, extensions as $$
  select net.http_post(url := 'https://ybdqdpwfhgngggaomvqq.supabase.co/functions/v1/' || p_fn || coalesce(p_qs, ''),
                       headers := jsonb_build_object('Authorization', 'Bearer ' || (select v from ct_secret where k = 'ct_anon_key'), 'Content-Type', 'application/json'),
                       body := '{}'::jsonb, timeout_milliseconds := 150000) $$;
select cron.schedule('ct-prices',        '50 15 * * 1-5',        $$select ct_call('ct-prices')$$);          -- 21:20 IST, after BP's 21:00 price load
select cron.schedule('ct-prices-retry',  '20,50 16-17 * * 1-5',   $$select ct_call('ct-prices')$$);          -- 21:50-23:20 IST catch-ups
select cron.schedule('ct-es-reset-eve',  '35 15 * * *',           $$select ct_call('ct-es', '?reset=1')$$);  -- 21:05 IST
select cron.schedule('ct-es-reset-late', '5 18 * * *',            $$select ct_call('ct-es', '?reset=1')$$);  -- 23:35 IST
select cron.schedule('ct-es-reset-am',   '35 2 * * *',            $$select ct_call('ct-es', '?reset=1')$$);  -- 08:05 IST
select cron.schedule('ct-es-continue',   '*/10 15-19,2-3 * * *',  $$select ct_call('ct-es')$$);
select cron.schedule('ct-ss-reset-eve',  '35 17 * * *',           $$select ct_call('ct-ss', '?reset=1')$$);  -- 23:05 IST
select cron.schedule('ct-ss-reset-am',   '0 3 * * *',             $$select ct_call('ct-ss', '?reset=1')$$);  -- 08:30 IST
select cron.schedule('ct-ss-continue',   '*/10 17-20,3-5 * * *',  $$select ct_call('ct-ss')$$);              -- resumes after rate limits
select cron.schedule('ct-build-eve',     '20 17 * * *',           $$select ct_nightly()$$);                  -- 22:50 IST
select cron.schedule('ct-build-night',   '50 18 * * *',           $$select ct_nightly()$$);                  -- 00:20 IST
select cron.schedule('ct-build-am',      '45 4 * * *',            $$select ct_nightly()$$);                  -- 10:15 IST
