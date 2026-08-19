"""
EquiSense.ai daily pull — Results (Q1 FY27) + Concalls (Q1 FY27).

Endpoints (verified 15 Aug 2026):
  Results   GET /api/v1/discover/results/glance?page=N&pageSize=20&quarter=1&fy=2027&sortCol=ecsScore&sortDir=desc
  Concalls  GET /api/v1/concalls?page=N&pageSize=20&quarter=1&fy=2027

Both 0-indexed, self-describing pagination (totalPages, hasNext).
Auth: cookie header from browser (env var EQUISENSE_COOKIE).

Emits two Excel files matching v2 schema so build_terminal.py reads them unchanged:
  - EquiSense - Full Dataset (Results + Concalls).xlsx  (3 sheets)
  - EquiSense Concalls - All Data.xlsx                  (1 sheet)
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path
import requests
import pandas as pd

BASE = 'https://equisense.ai'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ConfluenceTerminal/3'
PAGE_SIZE = 20
DEFAULT_QUARTER = int(os.environ.get('ES_QUARTER', '1'))
DEFAULT_FY = int(os.environ.get('ES_FY', '2027'))
DELAY_SEC = 0.25  # respectful pacing


def _session(cookie: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        'User-Agent': UA,
        'Accept': 'application/json',
        'Referer': 'https://equisense.ai/discover/results',
        'cookie': cookie,
    })
    return s


def _fetch_paginated(sess, path, quarter, fy, ckpt_path: Path, extra=''):
    """Fetch all pages, checkpointing after each page. Resumes on rerun."""
    ckpt = {'page': 0, 'rows': []}
    if ckpt_path.exists():
        ckpt = json.loads(ckpt_path.read_text())
        print(f"  [resume] page={ckpt['page']} rows={len(ckpt['rows'])}")

    page = ckpt['page']
    while True:
        url = f"{BASE}{path}?page={page}&pageSize={PAGE_SIZE}&quarter={quarter}&fy={fy}{extra}"
        r = sess.get(url, timeout=30)
        if r.status_code == 401:
            raise RuntimeError(f"401 Unauthorized — EquiSense cookie expired. Refresh EQUISENSE_COOKIE.")
        if r.status_code == 429:
            print(f"  [429] backing off 60s...")
            time.sleep(60); continue
        r.raise_for_status()
        j = r.json()
        content = j.get('content', j.get('data', []))
        total_pages = j.get('totalPages', 1)
        has_next = j.get('hasNext', page < total_pages - 1)
        ckpt['rows'].extend(content)
        ckpt['page'] = page + 1
        ckpt_path.write_text(json.dumps(ckpt))
        print(f"  page {page+1}/{total_pages} · +{len(content)} rows · total {len(ckpt['rows'])}")
        if not has_next or not content:
            break
        page += 1
        time.sleep(DELAY_SEC)
    return ckpt['rows']


def _pick(d, *keys, default=None):
    """Return the first non-None value from any of the candidate keys.
    Tolerates snake_case, camelCase, and Title Case variants without editing the
    caller. Extend the tuple list here if you spot a new API key naming."""
    if not isinstance(d, dict): return default
    for k in keys:
        v = d.get(k)
        if v is not None and v != '': return v
    return default


def _extract_result_row(r):
    """Map ES /discover/results/glance record → row matching v2 Results sheet schema.
    Every field passes through _pick() with fallback JSON-key candidates so the
    mapping stays robust across minor API renames."""
    ki = _pick(r, 'keyInsights', 'key_insights', 'insights')
    if isinstance(ki, list):
        ki = ' || '.join([f"[{_pick(i,'tag','category','sentiment',default='NEUTRAL')}] "
                          f"{_pick(i,'text','insight','description',default='')}"
                          for i in ki if isinstance(i, dict)])
    return {
        'Symbol': _pick(r, 'symbol', 'ticker', 'nseSymbol'),
        'Company': _pick(r, 'companyName', 'name', 'company'),
        'Sector': _pick(r, 'sector', 'sectorName'),
        'Date': _pick(r, 'resultDate', 'date', 'declarationDate'),
        'Time': _pick(r, 'resultTime', 'time'),
        'Market Cap (Cr)': _pick(r, 'marketCap', 'marketCapCr', 'mcap'),
        'Revenue (Cr)': _pick(r, 'revenue', 'revenueCr', 'sales'),
        'EBITDA (Cr)': _pick(r, 'ebitda', 'ebitdaCr'),
        'PAT (Cr)': _pick(r, 'pat', 'patCr', 'netProfit'),
        'OPM %': _pick(r, 'opm', 'operatingMargin', 'opmPct'),
        'Diluted EPS': _pick(r, 'dilutedEps', 'eps', 'epsDiluted'),
        'Rev YoY %': _pick(r, 'revenueYoy', 'revYoy', 'revenueYoYPct'),
        'EBITDA YoY %': _pick(r, 'ebitdaYoy', 'ebitdaYoYPct'),
        'PAT YoY %': _pick(r, 'patYoy', 'patYoYPct', 'netProfitYoy'),
        'OPM YoY (bps)': _pick(r, 'opmYoyBps', 'opmYoyBpsChange', 'opmDeltaYoyBps'),
        'EPS YoY %': _pick(r, 'epsYoy', 'epsYoYPct'),
        'Rev QoQ %': _pick(r, 'revenueQoq', 'revQoq'),
        'EBITDA QoQ %': _pick(r, 'ebitdaQoq'),
        'PAT QoQ %': _pick(r, 'patQoq'),
        'OPM QoQ (bps)': _pick(r, 'opmQoqBps', 'opmQoqBpsChange'),
        'EPS QoQ %': _pick(r, 'epsQoq'),
        'Result Verdict': _pick(r, 'resultVerdict', 'verdict'),
        'Verdict Reason': _pick(r, 'verdictReason', 'verdictExplanation'),
        'Balance Sheet Health': _pick(r, 'balanceSheetHealth', 'bsHealth', 'bshTag'),
        'PEAD Index': _pick(r, 'peadIndex', 'pead'),
        'AI Tag (PEAD Label)': _pick(r, 'peadLabel', 'aiTag', 'peadTag'),
        'PEAD Reason': _pick(r, 'peadReason', 'peadExplanation', 'driftReason'),
        'Drift Confidence': _pick(r, 'driftConfidence', 'peadConfidence'),
        'ECS Score': _pick(r, 'ecsScore', 'ecs'),
        'Price Move Since Result %': _pick(r, 'priceMoveSinceResult', 'priceMove', 'postResultReturn'),
        'Result Day Open': _pick(r, 'resultDayOpen', 'openOnResultDay'),
        'Current Price': _pick(r, 'currentPrice', 'ltp', 'lastPrice'),
        'Verdict Based on Concall': _pick(r, 'verdictBasedOnConcall'),
        'Data Verified': _pick(r, 'dataVerified'),
        'Result Summary': _pick(r, 'resultSummary', 'summary', 'aiSummary'),
        'Key Insights': ki,
        'ISIN': _pick(r, 'isin', 'ISIN'),
        'PDF URL': _pick(r, 'pdfUrl', 'sourcePdf', 'sourcePdfUrl', 'filingUrl'),
    }


def _extract_concall_row(r):
    fms = _pick(r, 'forwardMetrics', 'forward_metrics', 'metrics') or []
    def _fm(i):
        if i >= len(fms): return None
        m = fms[i]
        if isinstance(m, str): return m
        name = _pick(m, 'name', 'metric', 'label', default='')
        fy = _pick(m, 'fiscalYear', 'fy', 'year', default='')
        val = _pick(m, 'value', 'target', 'guidance', default='')
        ctx = _pick(m, 'context', 'reason', 'notes', default='')
        return f"{name} ({fy}): {val} — {ctx}"
    tags = _pick(r, 'tags', 'themes', 'categories')
    tags_str = ', '.join(tags) if isinstance(tags, list) else tags
    return {
        'Symbol': _pick(r, 'symbol', 'ticker'),
        'Company': _pick(r, 'companyName', 'name'),
        'Sector': _pick(r, 'sector'),
        'Date': _pick(r, 'concallDate', 'date', 'callDate'),
        'Time': _pick(r, 'concallTime', 'time'),
        'Market Cap (Cr)': _pick(r, 'marketCap', 'mcap'),
        'ECS Score': _pick(r, 'ecsScore', 'ecs'),
        'Guidance Move': _pick(r, 'guidanceMove', 'guidance', 'guidanceDirection'),
        'PEAD Index': _pick(r, 'peadIndex', 'pead'),
        'Forward Metrics Count': len(fms),
        'Tags': tags_str,
        'Summary': _pick(r, 'summary', 'aiSummary', 'concallSummary'),
        'Management Guidance': _pick(r, 'managementGuidance', 'guidance', 'mgmtCommentary'),
        'Forward Metric 1': _fm(0),
        'Forward Metric 2': _fm(1),
        'Forward Metric 3': _fm(2),
        'ISIN': _pick(r, 'isin', 'ISIN'),
        'Recording Link': _pick(r, 'recordingLink', 'recording', 'audioUrl', 'concallAudio'),
    }


def build_merged(res_df, conc_df):
    """3-sheet workbook matching v2 schema."""
    m = res_df.merge(
        conc_df.add_suffix(' (Concall)').rename(columns={'ISIN (Concall)':'ISIN_c','Symbol (Concall)':'Symbol_c'}),
        left_on='ISIN', right_on='ISIN_c', how='inner'
    )
    cols = ['Symbol', 'Company', 'Sector', 'Date', 'Market Cap (Cr)',
            'Revenue (Cr)', 'Rev YoY %', 'EBITDA (Cr)', 'EBITDA YoY %',
            'PAT (Cr)', 'PAT YoY %', 'OPM %', 'OPM YoY (bps)',
            'Result Verdict', 'Balance Sheet Health', 'AI Tag (PEAD Label)',
            'PEAD Index', 'ECS Score', 'ECS Score (Concall)',
            'Price Move Since Result %', 'Guidance Move (Concall)',
            'Date (Concall)', 'Tags (Concall)', 'Result Summary',
            'Summary (Concall)', 'Management Guidance (Concall)',
            'Forward Metric 1 (Concall)', 'Forward Metric 2 (Concall)',
            'Forward Metric 3 (Concall)', 'ISIN', 'PDF URL', 'Recording Link (Concall)']
    # Rename to match v2 merged sheet column names
    rename_map = {
        'Date': 'Result Date',
        'Guidance Move (Concall)': 'Guidance Move (Concall)',
        'Date (Concall)': 'Concall Date',
        'Tags (Concall)': 'Tags',
        'Summary (Concall)': 'Concall Summary',
        'Management Guidance (Concall)': 'Management Guidance',
        'Forward Metric 1 (Concall)': 'Forward Metric 1',
        'Forward Metric 2 (Concall)': 'Forward Metric 2',
        'Forward Metric 3 (Concall)': 'Forward Metric 3',
        'Recording Link (Concall)': 'Recording Link',
        'ECS Score': 'ECS Score (Results)',
    }
    for c in cols:
        if c not in m.columns: m[c] = None
    m = m[cols].rename(columns=rename_map)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default='data', type=Path)
    ap.add_argument('--quarter', type=int, default=DEFAULT_QUARTER)
    ap.add_argument('--fy', type=int, default=DEFAULT_FY)
    args = ap.parse_args()
    args.out_dir.mkdir(exist_ok=True, parents=True)

    cookie = os.environ.get('EQUISENSE_COOKIE')
    if not cookie:
        sys.exit("EQUISENSE_COOKIE env var not set. See README for cookie refresh.")

    sess = _session(cookie)
    ckpt_dir = args.out_dir / '_ckpt'
    ckpt_dir.mkdir(exist_ok=True)

    print("[ES] Fetching Results…")
    res_raw = _fetch_paginated(sess, '/api/v1/discover/results/glance',
                               args.quarter, args.fy,
                               ckpt_dir / f'es_results_Q{args.quarter}FY{args.fy}.json',
                               extra='&sortCol=ecsScore&sortDir=desc')
    print(f"[ES] Fetched {len(res_raw)} results")

    print("[ES] Fetching Concalls…")
    conc_raw = _fetch_paginated(sess, '/api/v1/concalls',
                                args.quarter, args.fy,
                                ckpt_dir / f'es_concalls_Q{args.quarter}FY{args.fy}.json')
    print(f"[ES] Fetched {len(conc_raw)} concalls")

    res_df = pd.DataFrame([_extract_result_row(r) for r in res_raw])
    conc_df = pd.DataFrame([_extract_concall_row(r) for r in conc_raw])

    # Write standalone concalls file
    conc_out = args.out_dir / 'EquiSense Concalls - All Data.xlsx'
    with pd.ExcelWriter(conc_out, engine='openpyxl') as w:
        conc_df.to_excel(w, 'EquiSense Concalls', index=False)
    print(f"[ES] Wrote {conc_out} ({len(conc_df)} rows)")

    # Write full 3-sheet workbook
    full_out = args.out_dir / 'EquiSense - Full Dataset (Results + Concalls).xlsx'
    merged_df = build_merged(res_df, conc_df)
    with pd.ExcelWriter(full_out, engine='openpyxl') as w:
        merged_df.to_excel(w, 'Merged (Results+Concall)', index=False)
        res_df.to_excel(w, 'Results (All)', index=False)
        conc_df.to_excel(w, 'Concalls (All)', index=False)
    print(f"[ES] Wrote {full_out}: Merged {len(merged_df)}, Results {len(res_df)}, Concalls {len(conc_df)}")

    # Clean checkpoints on success
    for f in ckpt_dir.glob('es_*.json'): f.unlink()


if __name__ == '__main__':
    main()
