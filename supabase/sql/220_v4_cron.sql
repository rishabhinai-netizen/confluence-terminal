-- v4 schedules (13 Oct 2026): the same three jobs now run ct4_nightly() (Results Leaders + Trend + Swing + page JSON). UTC times.
select cron.schedule('ct-v3-build-eve',   '10 18 * * *', $$select ct4_nightly()$$);   -- 23:40 IST
select cron.schedule('ct-v3-build-night', '10 19 * * *', $$select ct4_nightly()$$);   -- 00:40 IST
select cron.schedule('ct-v3-build-am',    '30 3 * * *',  $$select ct4_nightly()$$);   -- 09:00 IST
