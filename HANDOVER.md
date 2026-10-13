# Confluence Terminal v3 — HANDOVER (read first in a new chat)

Written 13 Oct 2026 (v3 go-live: "Results Leaders" model). Owner: Rishabh. Keep separate from Breakout Playbook (own chat, own Supabase project).

## Starter message
> Continue my Confluence Terminal v3. Read `HANDOVER.md` and `research/README.md` in my private repo
> `rishabhinai-netizen/confluence-terminal` (attach with add_repo, then clone) and memory `/areas/confluence-terminal.md`.

## 1. What it is now
One strategy, run as a 15-slot model portfolio, recomputed every night:
- Score every quarterly result against the **previous season's** results: growth ×2 (revenue YoY, PAT YoY, EPS change vs price, OPM change) + trend (vs 200-day avg, vs 52-week high, 200-day slope, 6-month excess run) + market reaction.
- Buy the top 10% (pr ≥ 0.90) within 10 sessions of the first post-result close, at the close; skip guidance CUT and balance sheet STRESSED; universe mcap ≥ ₹1,000 cr, turnover ≥ ₹5 cr.
- 15 slots; new-buy size = market gauge (vote of 3: EW index > 100-day avg, % stocks > 50-day > 50, 52w highs > lows). Gauge never forces sales.
- Sell at the close 60 sessions later. No stops.
Evidence: `research/README.md` (v3) and the research report artifact (link in the page's "Why these rules").

## 2. Where everything is
| Thing | Where |
|---|---|
| Page | https://confluence-terminal.pages.dev — Cloudflare Pages project `confluence-terminal`, Access app "Confluence Terminal" (id bff0ff80-78be-446c-8039-c49a1486c7d4), email rishabhinai@gmail.com |
| Database | Supabase `confluence-terminal`, id **ybdqdpwfhgngggaomvqq** |
| Secrets | table `ct_secret` (RLS, no policies). Read via SQL; never paste into repo/memory |
| Prices | read-only from Breakout Playbook feed functions (`ct_feed_*`, gated by `bp_secret.ct_feed_key`) → `ct_prices` (2024-01 onward in CT) |
| Code | `supabase/sql/100_v3_engine.sql`, `110_v3_page.sql`, `120_v3_cron.sql`; `web/index.src.html` (+ `_worker.js`); `research/v3/` |
| v2 | page archived at `legacy/web_v2/index.html`; v2 SQL (000–050) still installed, its builds unscheduled |

## 3. Nightly flow (IST)
21:05 EquiSense job → 21:20 prices (retries to 23:20) → 23:05 StockScans (breadth etc., resumes every 10 min) →
**23:40 `ct_v3_nightly()`** (+ 00:40 and 09:00 catch-ups). Steps: concall guidance sync → `ct_v3_market()` (EW index,
SMA100, breadth from the StockScans snapshot) → `ct_v3_features(q-1)` + `ct_v3_score(q-1)` for the live seasons →
`ct_model_advance()` (only through sessions whose prices and breadth are complete) → `ct_v3_page_data()` into `ct_page('data')`.
Health: `select kind, run_at, ok, note from ct_runs order by run_at desc limit 10;`  Manual run: `select ct_v3_nightly();` (~30 s).

Tables: `ct_days3`, `ct_mkt3`, `ct_breadth`, `ct_ev3` (features, scores, pr), `ct_model_pos` (`open` flag), `ct_model_trade`,
`ct_model_day` (equity curve), `ct_model_orders` (decided at close d, executed at the next close).
The model was replayed from 1 Jan 2025 with the live code; live from 13 Oct 2026.

## 4. Page deploy
Build: `CT_WORK=<work dir> python3 research/v3/build_site.py <report_url> '<validation json>'` writes `<work>/site/`
(evidence numbers come from `<work>/data/report.json`, produced by `research/v3/report_data.py`). Then
`CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=… npx wrangler pages deploy <work>/site --project-name confluence-terminal --branch main`
(token and account id in `ct_secret`).

## 5. Open items
1. **Repo still public** → Rishabh to switch to private (GitHub Settings → General → Danger zone).
2. StockScans cookie expires **21 Oct 2026** → fresh Copy-as-cURL; update `ct_secret.stockscans_cookie`. Breadth (one gauge vote) depends on it; without it the gauge falls back to the last known breadth.
3. `ct_ev` (v2, ~99 MB) can be truncated to free space (DB ~350 MB of 500 MB). Needs an approval prompt.
4. Watch-only hints (≈1 year of data, not rules): bulk/block buys ≥0.5% mcap positive; non-promoter insider selling negative; order-win filings no edge. Re-test once 2+ years exist.
5. Don't change rules on a few weeks of live data; review the live vs simulated record each season.

## 6. Lessons
- EquiSense `ecsScore`, `marketCap`, `pe` in history are TODAY's values → never backtest them.
- Rank against the previous season only (no look-ahead). Results filed >120 days after quarter end are restatements.
- Simulator: at gauge 0 do not create zero-weight placeholder positions (bug fixed 13 Oct in `sim2.py`).
- BSE 500 / Sensex series from StockScans have a 19-month gap (2024-04 → 2025-11): use Nifty 50 / Smallcap 250.
- Supabase MCP migrations containing DELETE/DROP/TRUNCATE trigger an approval prompt; write upserts/flags instead.
- `ct_prices.c` is float4: `round(double precision, int)` helper exists in CT.
