"""
StockScans.in daily pull.

Endpoints (verified 15 Aug 2026):
  Concalls    POST /api/company/concall-scan               body {"offset": N}
  Scans list  GET  /api/company/scans/popular              → 31 scan definitions
  Scan run    POST /api/company/scans/run                  body {ratiosType, timePeriod, scan, watchlistIds, order, orderBy, offset}
  Mkt table   POST /api/company/market-scans/table         body {"marketScanType":"Index"|"Industry","timePeriod":"Latest"}
  Mkt const.  POST /api/company/market-scans/constituents  body {name, marketScanType, timePeriod}

Auth: cookie header from env STOCKSCANS_COOKIE.

Rate limiting: hard ceiling around 90-100 requests per rolling window.
Recovery is 8-15 min. Script checkpoints after every response.
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path
import requests
import pandas as pd

BASE = 'https://www.stockscans.in'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ConfluenceTerminal/3'
PAGE_SIZE = 50
DELAY_SEC = 0.6                 # normal pacing
COOLDOWN_SEC = 12 * 60          # rate-limit cool-off
MAX_COOLDOWNS = 3               # give up after this many


def _session(cookie: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        'User-Agent': UA, 'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Referer': 'https://www.stockscans.in/',
        'cookie': cookie,
    })
    return s


class RateLimited(Exception): pass


def _post(sess, path, body):
    for attempt in range(2):
        r = sess.post(BASE + path, json=body, timeout=45)
        if r.status_code == 401:
            raise RuntimeError("401 Unauthorized — StockScans cookie expired. Refresh STOCKSCANS_COOKIE.")
        if r.status_code == 429 or 'Too many requests' in r.text[:200]:
            raise RateLimited(f"429 on {path}")
        if r.status_code >= 500:
            time.sleep(3); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Repeated 5xx from {path}")


def _get(sess, path):
    r = sess.get(BASE + path, timeout=45)
    if r.status_code == 401: raise RuntimeError("401 — SS cookie expired.")
    if r.status_code == 429: raise RateLimited(f"429 on {path}")
    r.raise_for_status()
    return r.json()


def _cool_off(cooldowns):
    print(f"  [rate-limit] cool-off #{cooldowns+1} for {COOLDOWN_SEC//60} min…")
    time.sleep(COOLDOWN_SEC)


# ---------- CONCALLS ----------
def pull_concalls(sess, out_dir, ckpt_dir):
    ckpt = ckpt_dir / 'ss_concalls.json'
    state = {'offset': 0, 'rows': []}
    if ckpt.exists(): state = json.loads(ckpt.read_text()); print(f"  [resume] offset={state['offset']} rows={len(state['rows'])}")

    cooldowns = 0
    while True:
        try:
            j = _post(sess, '/api/company/concall-scan', {'offset': state['offset']})
        except RateLimited:
            if cooldowns >= MAX_COOLDOWNS: print("  [give up] cooldowns exhausted; resume tomorrow"); break
            _cool_off(cooldowns); cooldowns += 1; continue
        rows = j.get('rows') or j.get('data') or []
        state['rows'].extend(rows)
        nxt = j.get('next')
        print(f"  offset {state['offset']} · +{len(rows)} rows · total {len(state['rows'])} · next={nxt}")
        if not nxt:
            break
        state['offset'] = nxt
        ckpt.write_text(json.dumps(state))
        time.sleep(DELAY_SEC)

    def _pick(d, *keys, default=None):
        for k in keys:
            v = d.get(k)
            if v is not None and v != '': return v
        return default

    def _row(r):
        hl = _pick(r, 'highlights', 'concallHighlights', 'keyPoints') or []
        if not isinstance(hl, list): hl = []
        return {
            'Exchange': _pick(r, 'exchange'),
            'Ticker': _pick(r, 'ticker', 'symbol', 'nseSymbol'),
            'Company': _pick(r, 'companyName', 'name', 'company'),
            'Sector': _pick(r, 'sector', 'industry', 'sectorName'),
            'Date': _pick(r, 'date', 'concallDate', 'resultDate'),
            'Time': _pick(r, 'time', 'concallTime'),
            'Result Quality Score': _pick(r, 'resultQualityScore', 'qualityScore', 'qualityScoreOutOf100'),
            'Result Quality Tier': _pick(r, 'resultQualityTier', 'qualityTier', 'tier'),
            'Mgmt Sentiment': _pick(r, 'mgmtSentiment', 'sentiment', 'managementSentiment'),
            'Has Transcript': 'Yes' if _pick(r, 'hasTranscript', 'transcriptAvailable') else 'No',
            'Has PPT': 'Yes' if _pick(r, 'hasPpt', 'pptAvailable') else 'No',
            'Highlight 1': hl[0] if len(hl) > 0 else None,
            'Highlight 2': hl[1] if len(hl) > 1 else None,
            'Highlight 3': hl[2] if len(hl) > 2 else None,
            'Summary PDF ID': _pick(r, 'summaryPdfId', 'summaryPdf', 'summaryPdfUrl'),
            'PPT PDF ID': _pick(r, 'pptPdfId', 'pptPdf', 'pptUrl'),
        }
    df = pd.DataFrame([_row(r) for r in state['rows']])
    out = out_dir / 'Concall Scans - All Data.xlsx'
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, 'Concall Scans', index=False)
    print(f"[SS] Wrote {out} ({len(df)} rows)")
    if ckpt.exists(): ckpt.unlink()


# ---------- MARKET SCANS ----------
def pull_market_scans(sess, out_dir, ckpt_dir):
    ckpt = ckpt_dir / 'ss_market.json'
    state = {'phase': 'summary', 'idx': [], 'ind': [], 'const_done': [], 'const_rows': [], 'hist_rows': []}
    if ckpt.exists(): state = json.loads(ckpt.read_text())

    cooldowns = 0
    def _do(payload_type):
        nonlocal cooldowns
        while True:
            try:
                return _post(sess, '/api/company/market-scans/table',
                             {'marketScanType': payload_type, 'timePeriod': 'Latest'})
            except RateLimited:
                if cooldowns >= MAX_COOLDOWNS: raise
                _cool_off(cooldowns); cooldowns += 1

    if state['phase'] == 'summary':
        print("  [SS market] pulling Index summary…")
        state['idx'] = _do('Index').get('table', [])
        time.sleep(DELAY_SEC)
        print(f"  [SS market] pulling Industry summary… (got {len(state['idx'])} indices)")
        state['ind'] = _do('Industry').get('table', [])
        print(f"  [SS market] {len(state['ind'])} industries")
        state['phase'] = 'constituents'
        ckpt.write_text(json.dumps(state))

    buckets = ([('Index', b['name']) for b in state['idx']] +
               [('Industry', b['name']) for b in state['ind']])
    done = set(tuple(x) for x in state['const_done'])

    for kind, name in buckets:
        if (kind, name) in done: continue
        try:
            j = _post(sess, '/api/company/market-scans/constituents',
                      {'name': name, 'marketScanType': kind, 'timePeriod': 'Latest'})
        except RateLimited:
            if cooldowns >= MAX_COOLDOWNS: print("  [give up] cooldowns exhausted; resume tomorrow"); break
            _cool_off(cooldowns); cooldowns += 1; continue
        for c in j.get('table', []):
            state['const_rows'].append({
                'Bucket Type': kind, 'Bucket Name': name,
                'Symbol': c.get('symbol') or c.get('companyId'),
                'Company Name': c.get('name') or c.get('companyName'),
                'Score': c.get('score'), 'Score Change (1M)': c.get('scoreChange'),
                'Status': c.get('status'),
            })
            # Also flatten historic score history
            for hs in (c.get('historicScores') or []):
                if isinstance(hs, list) and len(hs) >= 2:
                    state['hist_rows'].append({
                        'Bucket Type': kind, 'Bucket Name': name,
                        'Date': hs[0], 'Score': hs[1],
                        'Status': hs[2] if len(hs) > 2 else None,
                    })
        state['const_done'].append([kind, name])
        ckpt.write_text(json.dumps(state))
        if len(state['const_done']) % 10 == 0:
            print(f"  [SS market] processed {len(state['const_done'])}/{len(buckets)} buckets")
        time.sleep(DELAY_SEC)

    # Deduplicate hist rows (bucket may appear via both index and industry drill-down)
    hist_df = pd.DataFrame(state['hist_rows']).drop_duplicates(subset=['Bucket Type','Bucket Name','Date'])

    def _bucket_summary(bs, kind):
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
        _bucket_summary(state['idx'], 'Index').to_excel(w, 'Index Summary', index=False)
        _bucket_summary(state['ind'], 'Industry').to_excel(w, 'Industry Summary', index=False)
        pd.DataFrame(state['const_rows']).to_excel(w, 'All Constituents', index=False)
        hist_df.to_excel(w, 'Score History (Daily)', index=False)
    print(f"[SS] Wrote {out}: Idx {len(state['idx'])}, Ind {len(state['ind'])}, Const {len(state['const_rows'])}, Hist {len(hist_df)}")
    if ckpt.exists(): ckpt.unlink()


# ---------- 26 PRE-BUILT SCANS ----------
def pull_scans(sess, out_dir, ckpt_dir):
    ckpt = ckpt_dir / 'ss_scans.json'
    state = {'defs': None, 'done_ids': [], 'sheets': {}}
    if ckpt.exists(): state = json.loads(ckpt.read_text())

    cooldowns = 0
    if state['defs'] is None:
        j = _get(sess, '/api/company/scans/popular')
        state['defs'] = j.get('scans') or j.get('data') or []
        ckpt.write_text(json.dumps(state))
    defs = state['defs']

    done = set(state['done_ids'])
    for d in defs:
        sid = d.get('scanId') or d.get('id') or d.get('scanName')
        sname = d.get('scanName') or d.get('name') or f"scan_{sid}"
        if sid in done: continue
        rows = []; offset = 0
        while True:
            body = {'ratiosType':'Scores','timePeriod':'Latest','scan': d,
                    'watchlistIds': [], 'order':'desc',
                    'orderBy':'Market Capitalization', 'offset': offset}
            try:
                j = _post(sess, '/api/company/scans/run', body)
            except RateLimited:
                if cooldowns >= MAX_COOLDOWNS:
                    print(f"  [give up on {sname}] cooldowns exhausted"); break
                _cool_off(cooldowns); cooldowns += 1; continue
            tbl = j.get('table') or []
            if not tbl: break
            headers = tbl[0]
            data_rows = tbl[1:]
            if not rows and data_rows:
                rows.append(headers)  # store headers once
            rows.extend(data_rows)
            total = j.get('total', len(rows)-1)
            print(f"  [{sname}] offset {offset} +{len(data_rows)} → {len(rows)-1} / {total}")
            if len(rows) - 1 >= total: break
            offset += PAGE_SIZE
            time.sleep(DELAY_SEC)
        if rows:
            headers = rows[0]
            data = rows[1:]
            state['sheets'][sname[:31]] = {'headers': headers, 'rows': data}
        state['done_ids'].append(sid)
        ckpt.write_text(json.dumps(state))

    # Write workbook
    out = out_dir / 'StockScans - All Scans (26 of 31).xlsx'
    index_rows = []
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        # Index sheet first
        for name, data in state['sheets'].items():
            df = pd.DataFrame(data['rows'], columns=data['headers'])
            df.to_excel(w, name, index=False)
            index_rows.append({'Scan Name': name, 'Rows': len(df)})
        pd.DataFrame(index_rows).to_excel(w, 'Index', index=False)
    print(f"[SS] Wrote {out} ({len(state['sheets'])} scans)")
    if ckpt.exists(): ckpt.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default='data', type=Path)
    ap.add_argument('--skip', nargs='*', default=[], choices=['concalls','market','scans'],
                    help='skip specific stages')
    args = ap.parse_args()
    args.out_dir.mkdir(exist_ok=True, parents=True)
    ckpt = args.out_dir / '_ckpt'; ckpt.mkdir(exist_ok=True)

    cookie = os.environ.get('STOCKSCANS_COOKIE')
    if not cookie: sys.exit("STOCKSCANS_COOKIE env var not set.")
    sess = _session(cookie)

    if 'concalls' not in args.skip:
        print("[SS] === Concalls ===")
        pull_concalls(sess, args.out_dir, ckpt)
    if 'market' not in args.skip:
        print("[SS] === Market Scans ===")
        pull_market_scans(sess, args.out_dir, ckpt)
    if 'scans' not in args.skip:
        print("[SS] === 26 Pre-built Scans ===")
        pull_scans(sess, args.out_dir, ckpt)


if __name__ == '__main__':
    main()
