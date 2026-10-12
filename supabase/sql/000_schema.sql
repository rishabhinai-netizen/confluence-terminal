-- Confluence Terminal v2 core schema (12 Oct 2026). Supabase project "confluence-terminal" (ybdqdpwfhgngggaomvqq, ap-south-1).
-- All tables RLS-on with no policies: only the service role and security-definer functions read them.
create table ct_secret (k text primary key, v text not null, note text, updated_at timestamptz default now());   -- cookies, keys (never in git)
create table ct_runs (id bigint generated always as identity primary key, kind text not null, as_of date, run_at timestamptz default now(), ok boolean, note jsonb);
create index on ct_runs(kind, run_at desc);
create table ct_stock (isin text primary key, sym text, name text, grp text, ss_id text, es_symbol text, sector text, industry text, mcap numeric, updated_at timestamptz default now());
create index on ct_stock(sym); create index on ct_stock(ss_id);
create table ct_stock_map (ss_id text primary key, isin text, how text, updated_at timestamptz default now());
create table ct_prices (isin text not null, d date not null, o real, h real, l real, c real, v bigint, primary key (isin, d));   -- mirror of BP adjusted prices
create index on ct_prices(d);
create table ct_price_fp (isin text primary key, fp text);
create table ct_market (d date primary key, breadth numeric, breadth_chg20 numeric, n_liquid int);                             -- BP breadth
create table ct_es_results (id text primary key, isin text, symbol text, q int, fy int, announced_at timestamptz, ecs numeric, verdict text, pead_label text, pead_index int, bsh text, raw jsonb not null, fetched_at timestamptz default now());
create table ct_es_concalls (id text primary key, isin text, symbol text, q int, fy int, concall_at timestamptz, guidance_revision text, guidance_delivery text, tone text, candor text, earnings_quality text, analyst_sentiment text, story_type text, raw jsonb not null, fetched_at timestamptz default now());
create table ct_es_smart (id text primary key, source text, deal_date date, isin text, symbol text, side text, net_value numeric, raw jsonb not null, fetched_at timestamptz default now());
create table ct_es_filings (id text primary key, kind text, isin text, symbol text, filed_at timestamptz, impact int, direction text, raw jsonb not null, fetched_at timestamptz default now());
create table ct_ss_scan_def (scan_id text primary key, name text, scan_type text, def jsonb not null, updated_at timestamptz default now());
create table ct_ss_scan (d date not null, scan_id text not null, ss_id text not null, primary key (d, scan_id, ss_id));         -- scan membership by day
create table ct_ss_concall (company_key text not null, quarter text not null, ss_id text, name text, industry text, concall_at timestamptz, result_score numeric, sentiment_tier int, congrats int, tags jsonb, raw jsonb, fetched_at timestamptz default now(), primary key (company_key, quarter));
create table ct_ss_market (d date not null, kind text not null, key text not null, name text, parent text, score numeric, status text, raw jsonb, primary key (d, kind, key));
create table ct_snapshot (k text not null, d date not null, body jsonb not null, primary key (k, d));                           -- job state, breadth, calendars
create table ct_signal_stats (signal text not null, family text, horizon int not null, period text not null, n int, hit numeric, med_excess numeric, mean_excess numeric, p25 numeric, p75 numeric, computed_at timestamptz default now(), primary key (signal, horizon, period));
create table ct_picks (d date not null, isin text not null, board text not null, rank int, entry numeric, stop numeric, reason jsonb, primary key (d, isin, board));
create table ct_page (id text primary key, html text, built_at timestamptz default now());                                       -- 'data' = page JSON
-- (+ indexes on isin / dates; ct_days, ct_mkt, ct_ev, ct_pick_log are created in 010/030)
