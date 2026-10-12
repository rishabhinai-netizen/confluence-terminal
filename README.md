# Confluence Terminal v2 (private)

Evidence-first decision page for NSE/BSE earnings season. Rebuilt from scratch on 12 Oct 2026.
Page: **https://confluence-terminal.pages.dev** (Cloudflare Access — only rishabhinai@gmail.com).

What it does every evening: pulls EquiSense (results, concalls, insider/bulk/SAST deals, catalysts) and StockScans
(37 scans, concall scores, sector scores, breadth, calendars), mirrors adjusted prices from the Breakout Playbook feed,
re-measures every rule against the market, and rebuilds one page:

- **Today** — market regime stamp (equal-weight index vs 50-day average), season scoreboard, what needs attention.
- **Drift buys** — strong quarter + positive reaction, ranked; every source side by side, contradictions flagged.
- **Red flags** — events that preceded underperformance (missed + fell, stressed balance sheet, guidance cut, bulk churn, insider selling).
- **In play** — large bulk deals; high-impact catalysts.
- **Sectors** — StockScans industry scores (context only: no measured edge).
- **Stock lookup** — dossier for any stock: sources, history of every event and what the stock did after.
- **Evidence** — each rule vs its baseline at 5/20/60 sessions, by regime; methodology; what was dropped and why.
- **Track record** — every pick logged since go-live, measured forward.

## Layout
| Path | What |
|---|---|
| `supabase/sql/` | schema, engine (market index, events, rules, stats), page data, nightly chain, cron |
| `supabase/functions/` | `ct-prices` (BP feed mirror), `ct-es` (EquiSense), `ct-ss` (StockScans), `ct-page` (serves data, key-gated), `ct-ingest` (backfills) |
| `web/` | `index.html` (the page) + `_worker.js` (Cloudflare Pages worker, proxies `/api/*` with the key) |
| `research/` | Python research + loaders; **`research/README.md` has every finding** |
| `legacy/` | v1–v8 (Aug–Sep 2026) builder, template, workflows, build 8 HTML — archived, not run |

Infra: Supabase project `confluence-terminal` (ybdqdpwfhgngggaomvqq, ap-south-1); secrets only in table `ct_secret`.
Deploy page: `wrangler pages deploy web --project-name confluence-terminal --branch main` (token in `ct_secret`).
Handover for a new chat: `HANDOVER.md`.
