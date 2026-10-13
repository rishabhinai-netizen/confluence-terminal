-- v3 schedules (13 Oct 2026). Times UTC; IST = UTC + 5:30.
-- The v2 builds (ct-build-eve/-night/-am -> ct_nightly) were unscheduled on 13 Oct; ingestion jobs from 050_cron.sql stay.
-- ct_v3_nightly is idempotent: the model only advances through sessions whose prices and breadth are complete (ct_model_ready).
select cron.schedule('ct-v3-build-eve',   '10 18 * * *', $$select ct_v3_nightly()$$);   -- 23:40 IST, after prices (21:20) and StockScans breadth (23:05)
select cron.schedule('ct-v3-build-night', '10 19 * * *', $$select ct_v3_nightly()$$);   -- 00:40 IST catch-up
select cron.schedule('ct-v3-build-am',    '30 3 * * *',  $$select ct_v3_nightly()$$);   -- 09:00 IST, morning results + fallback breadth
