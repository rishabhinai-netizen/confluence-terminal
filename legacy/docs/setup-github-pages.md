# One-time setup — get your live GitHub Pages URL

Total time: ~10 minutes. After this, the terminal auto-refreshes daily at
**07:00 IST** and is live at a URL you can bookmark and open on any device.

## Prerequisites

- GitHub account (free tier is fine — public or private repo both work; private
  repos on the free plan get 2,000 Actions minutes/month, plenty for one daily
  run of ~15-25 min)
- `gh` CLI installed and authenticated (`gh auth login`) — optional but faster
  than the web UI

## Step 1 — Create the repo and push the code

Unzip `Confluence Automation.zip` into a folder, then from inside that folder:

```bash
cd automation                              # the folder that has requirements.txt
git init -b main
git add .
git commit -m "Initial commit"

# Option A: private repo (recommended — cookies are secrets)
gh repo create confluence-terminal --private --source=. --remote=origin --push

# Option B: public repo (only if you're okay sharing the tool publicly;
# cookies stay hidden in Secrets either way)
gh repo create confluence-terminal --public --source=. --remote=origin --push
```

If you don't have `gh` CLI: create the repo manually on github.com, then:

```bash
git remote add origin https://github.com/<your-username>/confluence-terminal.git
git branch -M main
git push -u origin main
```

## Step 2 — Add the two session cookies as GitHub Secrets

In your browser, go to the repo → **Settings** → **Secrets and variables** →
**Actions** → **New repository secret**. Add two secrets:

| Name | Value |
|---|---|
| `STOCKSCANS_COOKIE` | The full cookie header string captured from `stockscans.in` (see `docs/cookie-refresh.md` for step-by-step) |
| `EQUISENSE_COOKIE` | The full cookie header string captured from `equisense.ai` |

## Step 3 — Enable GitHub Pages (this is the one non-obvious step)

Repo → **Settings** → **Pages** → under **Build and deployment**:

- **Source:** select **GitHub Actions** (not "Deploy from a branch")

That's it. Save. No custom domain needed; GitHub gives you a URL automatically.

## Step 4 — Kick off the first run manually

Repo → **Actions** tab → left sidebar → **Daily Confluence refresh** → click the
**Run workflow** button (top right of the page) → **Run workflow**.

The first run takes 15-25 minutes because it pulls the full dataset from
scratch. Watch the live log — the last step prints your live URL, which will
look like:

```
https://<your-username>.github.io/confluence-terminal/
```

Bookmark that URL. It's the same URL every day; only the content behind it
refreshes.

## What happens every day from now on

- **07:00 IST** — cron fires
- Pulls the previous session's fresh results + concalls from both sources
  (any that reported after the last run gets picked up)
- Rebuilds the HTML with the new conviction scores
- Commits the updated Excel data files back to `main`
- Deploys the new HTML to GitHub Pages — the URL updates in place

You don't need to do anything. When you open the URL in the morning it's
already refreshed. The masthead's "Built" timestamp confirms when the last
successful run finished.

## When something breaks

- **Workflow fails with `401 Unauthorized`** → one of the cookies expired. Open
  `docs/cookie-refresh.md`, capture a fresh cookie in Chrome, update the
  matching GitHub Secret, then re-run the workflow manually. Fix takes 2 min.
- **StockScans rate-limited mid-run** → the script checkpoints per API page.
  The workflow uses `continue-on-error: true` on that step so the HTML still
  builds from whatever was pulled, and the next day's run resumes any gaps.
- **Nothing changed in the data** → the commit step is idempotent; the
  workflow just re-deploys the same HTML.

## Cost check

Free tier gives you 2,000 Actions minutes/month on private repos, unlimited on
public. A typical daily run = 15-25 min. Even with worst-case 30 min × 26 days
= 780 min/month. Well within limits.

## Optional — get an alert when the pipeline breaks

Add one more workflow that runs weekly to decode the JWT `exp` claim in your
current `authtoken` and post to Telegram/email if it's ≤ 3 days away. Not built
here — flagging as roadmap item v3.1.
