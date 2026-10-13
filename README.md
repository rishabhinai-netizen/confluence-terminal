# Confluence Terminal v3 (private)

One strategy, run as a 15-slot model portfolio: **Results Leaders** — buy the top 10% of each results season (growth ×2 + trend +
market reaction, ranked against the previous season), hold 60 sessions, size new buys by a 3-vote market gauge.
Page: **https://confluence-terminal.pages.dev** (Cloudflare Access — only rishabhinai@gmail.com).

Every evening the page shows: market gauge · orders for tomorrow's close · the portfolio with exit dates · results inside the
buy window and why each is or isn't bought · the track record (replayed from Jan 2025, live from 13 Oct 2026) · the evidence ·
a lookup for any stock's latest result. Evidence: `research/README.md`.

## Layout
| Path | What |
|---|---|
| `supabase/sql/` | schema, engine (market index, events, rules, stats), page data, nightly chain, cron |
| `supabase/functions/` | `ct-prices` (BP feed mirror), `ct-es` (EquiSense), `ct-ss` (StockScans), `ct-page` (serves data, key-gated), `ct-ingest` (backfills) |
| `web/` | `index.src.html` (page template; built by `research/v3/build_site.py`) + `_worker.js` (Cloudflare Pages worker, proxies `/api/*` with the key) |
| `research/` | v2 scripts at top level; **v3 research in `research/v3/`**; **`research/README.md` has every finding** |
| `legacy/` | v1–v8 (Aug–Sep 2026) builder, template, workflows, build 8 HTML — archived, not run |

Infra: Supabase project `confluence-terminal` (ybdqdpwfhgngggaomvqq, ap-south-1); secrets only in table `ct_secret`.
Deploy page: build with `research/v3/build_site.py`, then `wrangler pages deploy <work>/site --project-name confluence-terminal --branch main` (token in `ct_secret`).
Handover for a new chat: `HANDOVER.md`.
