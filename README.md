# Confluence Terminal — Daily Automation + GitHub Pages

Pulls both sources every trading day, refreshes the 5 Excel workbooks +
rebuilds the HTML, and **deploys it to GitHub Pages as a live URL you can
bookmark**. Runs on GitHub Actions free tier — no server, no laptop dependency.

## → Get started: read `docs/setup-github-pages.md` first (one-time setup, ~10 min)

## What it does each morning

1. **07:00 IST** (01:30 UTC) — cron kicks off, Mon–Sat
2. `pull_equisense.py` — fetches Results (all pages, paginated) + Concalls (all pages)
3. `pull_stockscans.py` — fetches Concall Scans + Market Scans (Index + Industry + all constituents + 25 days score history) + all 26 pre-built scans with rate-limit-aware batching and per-page checkpointing
4. `build_terminal.py` — reads the freshly-written Excels and regenerates `public/index.html`
5. Commits the refreshed Excel files back to `main`
6. **Deploys the new HTML to GitHub Pages** — same URL, refreshed content

## First-time setup (once)

```bash
git init && gh repo create confluence-terminal --private --source=. --remote=origin --push
```

Then add two secrets in the repo settings (Settings → Secrets and variables → Actions):

- `STOCKSCANS_COOKIE` — the entire cookie header string from your browser
- `EQUISENSE_COOKIE` — the entire cookie header string from your browser

Format: paste the raw cookie string like
`_ga=…; authtoken=…; _clck=…; …`

## Refreshing cookies when they expire

Both tokens are JWTs with expiry (StockScans ~19 days, EquiSense ~90 days from
issue). When a workflow run fails with `401 Unauthorized`:

1. Log into stockscans.in (or equisense.ai) in Chrome
2. F12 → Network tab → Fetch/XHR filter → Preserve log ✓
3. Reload the page, wait for API calls
4. Right-click any API request → Copy → Copy as cURL (bash)
5. Extract the `cookie:` header value from the cURL string
6. Paste it into the GitHub secret (Settings → Secrets → Actions → update)

Detailed cookie-capture procedure lives in `docs/cookie-refresh.md`.

## Manual run (local test before enabling cron)

```bash
pip install -r requirements.txt
export STOCKSCANS_COOKIE="…"
export EQUISENSE_COOKIE="…"
python pull_equisense.py --out-dir data
python pull_stockscans.py --out-dir data
python build_terminal.py --data-dir data --out "Confluence Terminal v3.html"
```

## Checkpointing (important)

StockScans has an aggressive rate limit (~90-100 requests / rolling window,
recovery 8-15 min). The pull scripts checkpoint to `data/_checkpoint_*.json`
after every page so a mid-run rate-limit hit loses zero progress — just
re-invoke the same script and it resumes from where it stopped.

The GitHub Actions job budgets 30 minutes total. If it dies to rate-limit
partway, the next day's run picks up the missing pieces because scanning
is idempotent per-day.

## What lives where

```
.
├── .github/workflows/daily.yml   ← cron trigger
├── pull_equisense.py             ← ES Results + Concalls pull
├── pull_stockscans.py            ← SS Concall + Scans + Market Scans pull
├── build_terminal.py             ← rebuild HTML from Excels
├── template.html                 ← HTML template (renders the payload)
├── requirements.txt
├── data/                         ← 5 Excel files, checkpoints, and generated HTML
│   ├── EquiSense - Full Dataset (Results + Concalls).xlsx
│   ├── EquiSense Concalls - All Data.xlsx
│   ├── Concall Scans - All Data.xlsx
│   ├── StockScans - All Scans (26 of 31).xlsx
│   ├── StockScans - Market Scans (Full).xlsx
│   └── Confluence Terminal v3.html
└── docs/
    └── cookie-refresh.md
```

## Roadmap

- **v3.1** — add Telegram/email alert on cookie expiry so you know before the run fails
- **v4** — migrate storage from Excel → Supabase for true historical trending
  (right now each day overwrites; historical trending needs a DB). Recommendation
  is to run this Excel-based setup for 2-3 weeks first to prove out the pipeline
  before adding DB complexity.
- **v5** — LLM narrative layer: per-top-pick Haiku call that writes a 150-word
  decisive brief pulling from Verdict Reason + Key Insights + Guidance
