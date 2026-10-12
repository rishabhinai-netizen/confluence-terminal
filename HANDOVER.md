# Confluence Terminal v2 — HANDOVER (read first in a new chat)

Written 12 Oct 2026 (v2 go-live). Owner: Rishabh. Keep separate from Breakout Playbook (own chat, own Supabase project).

## Starter message
> Continue my Confluence Terminal v2. Read `HANDOVER.md` and `research/README.md` in my private repo
> `rishabhinai-netizen/confluence-terminal` (attach with add_repo, then clone) and memory `/areas/confluence-terminal.md`.

## 1. Where everything is
| Thing | Where |
|---|---|
| Page | https://confluence-terminal.pages.dev — Cloudflare Pages project `confluence-terminal`, Access app "Confluence Terminal" (id bff0ff80-78be-446c-8039-c49a1486c7d4), policy: email rishabhinai@gmail.com, session 30 days |
| Database | Supabase `confluence-terminal`, id **ybdqdpwfhgngggaomvqq** (free plan, ap-south-1) |
| Secrets | table `ct_secret` (RLS, no policies): stockscans_cookie, equisense_cookie, bp_anon_key, bp_feed_key, page_key, ingest_key, ct_anon_key, cloudflare_api_token/account_id, github_token. Read via SQL; never paste into repo/memory |
| Prices | read-only from Breakout Playbook: BP functions `ct_feed_meta_lite`, `ct_feed_prices`, `ct_feed_prices_isins` (+ unused `ct_feed_meta`), gated by `bp_secret.ct_feed_key`. These are the only CT objects inside BP |
| Code | this repo (`supabase/`, `web/`, `research/`); v1–v8 in `legacy/` |
| Old public page | rishabhinai-netizen.github.io/confluence-terminal now shows a "no longer public" notice (12 Oct). **Repo is still public — Rishabh to switch it to private** (Settings → General → Danger zone → Change visibility); the session proxy cannot change repo settings |

## 2. Nightly flow (pg_cron in CT; times IST)
21:05 EquiSense job (results + concalls of live season, 7-day smart money, catalysts) → 21:20 prices from BP (retries
to 23:20) → 22:50 build → 23:05 StockScans job (resumes every 10 min through rate limits) → 23:35 EquiSense late pass →
00:20 build → 08:05 EquiSense + 08:30 StockScans morning passes → 10:15 build. `ct_nightly()` = market index → events →
late-filing filter → stats → log picks → page JSON into `ct_page('data')`. Each step logs to `ct_runs`.

Check health: `select kind, run_at, ok, note from ct_runs order by run_at desc limit 20;`
Run a build by hand: `select ct_nightly();` (≈70 s). Edge functions take `?reset=1` to restart today's job.

## 3. Rules (see research/README.md for numbers)
drift_buy (PAT ≥25%, rev ≥15%, reaction ≥3%; 10-session window; ranked by reaction; ≤2 per sector up top; green only
when market > 50-day average) · avoid_miss_fall · avoid_stressed · avoid_guidance_cut · guidance_missed ·
flag_bulk_churn · flag_insider_sell · in_play_bulk · (shown, no edge: guidance_raised, promoter_buy).
Defined in `ct_score_events()` (010_engine.sql). Adding a rule = add a CASE line there + label in web/index.html RULES.

## 4. Known gaps / next steps
1. **StockScans scan research**: history pull (`research/pull_ss_scanhist.py`) was mid-way on 12 Oct (month-ends from
   Jun 2026 back). Finish it, load into `ct_ss_scan` via ct-ingest, then study scan *entries* → add any scan with a real
   edge as a rule. Note: a dated snapshot for the current day is empty until StockScans fills it; daily pull uses "Latest".
2. StockScans cookie expires **21 Oct 2026** → Rishabh pastes a fresh Copy-as-cURL; update `ct_secret.stockscans_cookie`.
3. Forward-track the new concall fields (candor, tone, earnings quality) and StockScans result score; promote only with evidence.
4. Track record starts 12 Oct 2026 (`ct_pick_log`). Compare live vs history monthly; no rule changes on a few weeks of data.
5. Optional: StockEdge regime layer; guidance-vs-delivery history per company (EquiSense `guidanceDelivery` across quarters).
6. Axis Finance personal-dealing policy check before sharing any recos (open since Oct).

## 5. Lessons
- EquiSense `ecsScore`, `marketCap`, `pe` in history are TODAY's values → never backtest them.
- Supabase MCP migrations containing DELETE/DROP trigger an approval prompt; write upserts instead.
- PostgREST anon calls to BP time out at 8 s → keep feed functions light.
- GitHub API via this session proxy is repo-scoped (cannot create repos or touch Pages settings).
