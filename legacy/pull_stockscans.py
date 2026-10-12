"""AI-1 pull — Market Scans (fresh momentum) + 26 pre-built scans.

Deliberately skips the AI-1 concall stage (list-format response only carries
coarse tier codes, not the granular 0-100 Quality Score). Concall data stays
on the 15 Aug seeded file; Market Scans + 26 scans refresh daily.
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path
import requests
import pandas as pd

BASE = 'https://www.stockscans.in'
UA = 'Mozilla/5.0 ConfluenceTerminal/6'
DELAY = 0.6
COOLDOWN = 12 * 60
MAX_COOLDOWNS = 3


def _sess(ck):
    s = requests.Session()
    s.headers.update({'cookie': ck, 'User-Agent': UA, 'Accept': 'application/json',
                      'Content-Type': 'application/json', 'Referer': 'https://www.stockscans.in/'})
    return s


class RateLimited(Exception): pass


def _post(sess, path, body):
    for attempt in range(2):
        r = sess.post(BASE + path, json=body, timeout=45)
        if r.status_code == 401: raise RuntimeError('401 — AI-1 cookie expired')
        if r.status_code == 429 or 'Too many requests' in r.text[:200]:
            raise RateLimited(f'429 on {path}')
        if r.status_code >= 500: time.sleep(3); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f'Repeated 5xx from {path}')


def _get(sess, path):
    r = sess.get(BASE + path, timeout=45)
    if r.status_code == 401: raise RuntimeError('401 — AI-1 cookie expired')
    if r.status_code == 429: raise RateLimited(f'429 on {path}')
    r.raise_for_status()
    return r.json()


def _cool_off(cooldowns):
    print(f'  [rate-limit] cool-off #{cooldowns+1} for {COOLDOWN//60} min...')
    time.sleep(COOLDOWN)


def pull_market_scans(sess, out_dir):
    print('[AI-1 Market] pulling Index summary...')
    idx = _post(sess, '/api/company/market-scans/table',
                {'marketScanType': 'Index', 'timePeriod': 'Latest'}).get('table', [])
    time.sleep(DELAY)
    print(f'  {len(idx)} indices')
    print('[AI-1 Market] pulling Industry summary...')
    ind = _post(sess, '/api/company/market-scans/table',
                {'marketScanType': 'Industry', 'timePeriod': 'Latest'}).get('table', [])
    print(f'  {len(ind)} industries')

    buckets = ([('Index', b['name']) for b in idx] +
               [('Industry', b['name']) for b in ind])
    const_rows, hist_rows = [], []
    cooldowns = 0
    for i, (kind, name) in enumerate(buckets):
        try:
            j = _post(sess, '/api/company/market-scans/constituents',
                      {'name': name, 'marketScanType': kind, 'timePeriod': 'Latest'})
        except RateLimited:
            if cooldowns >= MAX_COOLDOWNS: print('  [give up] cooldowns exhausted'); break
            _cool_off(cooldowns); cooldowns += 1; continue
        for c in j.get('table', []):
            const_rows.append({
                'Bucket Type': kind, 'Bucket Name': name,
                'Symbol': c.get('symbol') or c.get('companyId'),
                'Company Name': c.get('name') or c.get('companyName'),
                'Score': c.get('score'), 'Score Change (1M)': c.get('scoreChange'),
                'Status': c.get('status'),
            })
            for hs in (c.get('historicScores') or []):
                if isinstance(hs, list) and len(hs) >= 2:
                    hist_rows.append({
                        'Bucket Type': kind, 'Bucket Name': name,
                        'Date': hs[0], 'Score': hs[1],
                        'Status': hs[2] if len(hs) > 2 else None,
                    })
        if (i+1) % 10 == 0: print(f'  processed {i+1}/{len(buckets)} buckets')
        time.sleep(DELAY)

    hist_df = pd.DataFrame(hist_rows).drop_duplicates(subset=['Bucket Type','Bucket Name','Date']) if hist_rows else pd.DataFrame()

    def _summary(bs, kind):
        return pd.DataFrame([{
            f'{kind} Name': b.get('name'),
            'Symbol': b.get('symbol') or b.get('companyId') or None,
            '# Companies': b.get('totalCompanies'),
            'Score': b.get('score'),
            'Score Change (1M)': b.get('scoreChange'),
            'Status': b.get('status'),
            'Last Updated': b.get('lastUpdated'),
        } for b in bs])

    out = out_dir / 'StockScans - Market Scans (Full).xlsx'
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        _summary(idx, 'Index').to_excel(w, sheet_name='Index Summary', index=False)
        _summary(ind, 'Industry').to_excel(w, sheet_name='Industry Summary', index=False)
        pd.DataFrame(const_rows).to_excel(w, sheet_name='All Constituents', index=False)
        (hist_df if not hist_df.empty else pd.DataFrame(columns=['Bucket Type','Bucket Name','Date','Score','Status'])).to_excel(w, sheet_name='Score History (Daily)', index=False)
    print(f'[AI-1 Market] wrote {out}: {len(idx)} idx, {len(ind)} ind, {len(const_rows)} const, {len(hist_df)} hist')


def pull_scans(sess, out_dir):
    print('[AI-1 Scans] discovering 26 pre-built scans...')
    j = _get(sess, '/api/company/scans/popular')
    defs = j.get('scans') or j.get('data') or []
    print(f'  {len(defs)} scan definitions')

    sheets = {}
    cooldowns = 0
    for d in defs:
        sname = (d.get('scanName') or d.get('name') or 'scan')[:31]
        rows = []; offset = 0
        while True:
            body = {'ratiosType':'Scores','timePeriod':'Latest','scan': d,
                    'watchlistIds': [], 'order':'desc',
                    'orderBy':'Market Capitalization', 'offset': offset}
            try:
                j = _post(sess, '/api/company/scans/run', body)
            except RateLimited:
                if cooldowns >= MAX_COOLDOWNS:
                    print(f'  [give up on {sname}] cooldowns exhausted'); break
                _cool_off(cooldowns); cooldowns += 1; continue
            tbl = j.get('table') or []
            if not tbl: break
            headers = tbl[0]; data_rows = tbl[1:]
            if not rows and data_rows: rows.append(headers)
            rows.extend(data_rows)
            total = j.get('total', len(rows)-1)
            if len(rows) - 1 >= total: break
            offset += 50
            time.sleep(DELAY)
        if rows:
            sheets[sname] = {'headers': rows[0], 'rows': rows[1:]}
            print(f'  [{sname}] {len(rows)-1} rows')

    out = out_dir / 'StockScans - All Scans (26 of 31).xlsx'
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        idx_rows = []
        for name, data in sheets.items():
            pd.DataFrame(data['rows'], columns=data['headers']).to_excel(w, sheet_name=name, index=False)
            idx_rows.append({'Scan Name': name, 'Rows': len(data['rows'])})
        pd.DataFrame(idx_rows).to_excel(w, sheet_name='Index', index=False)
    print(f'[AI-1 Scans] wrote {out}: {len(sheets)} scans')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default='data', type=Path)
    args = ap.parse_args()
    args.out_dir.mkdir(exist_ok=True, parents=True)
    ck = os.environ.get('STOCKSCANS_COOKIE')
    if not ck: sys.exit('STOCKSCANS_COOKIE not set.')
    s = _sess(ck)
    # DELIBERATELY SKIP concalls (list-format response has no granular scores anyway).
    # 15 Aug seeded 'Concall Scans - All Data.xlsx' remains in the repo untouched.
    print('[AI-1] === Market Scans (fresh momentum) ===')
    pull_market_scans(s, args.out_dir)
    print('\n[AI-1] === 26 Pre-built Scans (fresh signal stack) ===')
    pull_scans(s, args.out_dir)


if __name__ == '__main__':
    main()
