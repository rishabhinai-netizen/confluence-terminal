# Cookie refresh — step by step

Both StockScans and EquiSense use JWT session cookies with baked-in expiry.
When the daily workflow fails with `401 Unauthorized`, the token has expired
and needs a fresh capture from your browser.

## StockScans (expires roughly every 19 days)

1. Chrome → https://www.stockscans.in (log in if needed)
2. Press F12 → **Network** tab → filter to **Fetch/XHR** → tick **Preserve log**
3. In the site, click **Scans → Concall Scans** (this triggers an API call)
4. In the Network list, find `concall-scan` → right-click → **Copy → Copy as cURL (bash)**
5. In the cURL string, locate the `-H 'cookie: …'` line
6. Copy the entire cookie value (everything between the single quotes)
7. Go to your repo → Settings → Secrets and variables → Actions → `STOCKSCANS_COOKIE` → Update

The cookie value looks like:
```
_ga=GA1.1.…; authtoken=eyJ0eXAiOiJKV1Qi…; _clck=…; _ga_6GLNXH796V=…; _clsk=…
```

## EquiSense (expires roughly every 90 days)

1. Chrome → https://equisense.ai/discover/results (log in if needed)
2. F12 → Network → Fetch/XHR → Preserve log ✓
3. Reload the page (F5) → API calls fire automatically
4. Find `results/glance?…` → right-click → Copy → Copy as cURL
5. Extract the `cookie:` header value
6. Repo → Settings → Secrets → `EQUISENSE_COOKIE` → Update

Cookie value looks like:
```
es_anon_id=…; ES_AUTH=…; JSESSIONID=…
```

## Verify

After updating the secret, trigger the workflow manually:

Repo → Actions → **Daily Confluence refresh** → **Run workflow** button (top right)

If it completes cleanly, you're good for another cycle.

## Optional: proactive expiry alert

The `authtoken` JWT can be decoded to read its expiry. Consider adding a
weekly check that warns via Telegram/email 2 days before either cookie
expires so you refresh proactively instead of reactively. (Planned for v3.1.)
