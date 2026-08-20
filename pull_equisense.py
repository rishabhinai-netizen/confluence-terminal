"""AI-2 pull with real API field names."""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path
import requests, pandas as pd

BASE = 'https://equisense.ai'
UA = 'Mozilla/5.0 ConfluenceTerminal/6'
Q, FY = 1, 2027

def _epoch(e):
    if not e: return None
    try: return pd.to_datetime(int(e), unit='ms').strftime('%Y-%m-%d')
    except: return None

def _fetch_all(sess, path, extra=''):
    all_rows, page = [], 0
    while True:
        r = sess.get(f'{BASE}{path}?page={page}&pageSize=50&quarter={Q}&fy={FY}{extra}', timeout=30)
        if r.status_code == 401: raise RuntimeError('AI-2 cookie expired')
        if r.status_code == 429: time.sleep(60); continue
        r.raise_for_status()
        j = r.json()
        content = j.get('content', [])
        all_rows.extend(content)
        if page % 5 == 0: print(f'  page {page} total {len(all_rows)}')
        if not j.get('hasNext') or not content: break
        page += 1
        time.sleep(0.18)
    return all_rows

def _norm_results(raw):
    rows = []
    for r in raw:
        ins = r.get('insightsJson')
        ins_str = None
        if ins:
            try:
                x = json.loads(ins) if isinstance(ins, str) else ins
                if isinstance(x, list):
                    ins_str = ' || '.join([f"[{i.get('tag','NEUTRAL')}] {i.get('text','')}" for i in x if isinstance(i, dict)])
            except: ins_str = str(ins)[:2000]
        rows.append({
            'Symbol': r.get('symbol'), 'Company': r.get('companyName'),
            'Sector': r.get('companySector'), 'Date': _epoch(r.get('resultAnnouncementEpoch')), 'Time': None,
            'Market Cap (Cr)': r.get('marketCap'), 'Revenue (Cr)': r.get('revenue'),
            'EBITDA (Cr)': r.get('ebitda'), 'PAT (Cr)': r.get('profitAfterTax'),
            'OPM %': r.get('opm'), 'Diluted EPS': r.get('dilutedEPS'),
            'Rev YoY %': r.get('revenueYoyGrowth'), 'EBITDA YoY %': r.get('ebitdaYoyGrowth'),
            'PAT YoY %': r.get('patYoyGrowth'), 'OPM YoY (bps)': r.get('opmYoyBps'),
            'EPS YoY %': r.get('epsYoyGrowth'), 'Rev QoQ %': r.get('revenueSeqGrowth'),
            'EBITDA QoQ %': r.get('ebitdaSeqGrowth'), 'PAT QoQ %': r.get('patSeqGrowth'),
            'OPM QoQ (bps)': r.get('opmSeqBps'), 'EPS QoQ %': r.get('epsSeqGrowth'),
            'Result Verdict': r.get('resultVerdict'), 'Verdict Reason': r.get('resultVerdictReason'),
            'Balance Sheet Health': r.get('balanceSheetHealth'), 'PEAD Index': r.get('peadIndex'),
            'AI Tag (PEAD Label)': r.get('peadLabel'), 'PEAD Reason': r.get('peadReason'),
            'Drift Confidence': r.get('driftConfidence'), 'ECS Score': r.get('ecsScore'),
            'Price Move Since Result %': r.get('priceMovePct'),
            'Result Day Open': r.get('resultDayOpenPrice'), 'Current Price': r.get('currentPrice'),
            'Verdict Based on Concall': r.get('verdictBasedOnConcall'),
            'Data Verified': r.get('dataVerified'), 'Result Summary': r.get('resultSummaryText'),
            'Key Insights': ins_str, 'ISIN': r.get('isin'), 'PDF URL': r.get('pdfUrl'),
        })
    return pd.DataFrame(rows)

def _norm_concalls(raw):
    rows = []
    for r in raw:
        fms = r.get('forwardMetrics') or []
        def _fm(i):
            if i >= len(fms): return None
            m = fms[i]
            if isinstance(m, str): return m
            if isinstance(m, dict):
                return f"{m.get('name','')} ({m.get('fiscalYear', m.get('fy',''))}): {m.get('value','')}"
        tags = r.get('tags')
        rows.append({
            'Symbol': r.get('symbol'), 'Company': r.get('companyName'),
            'Sector': r.get('companySector'), 'Date': _epoch(r.get('concallEventEpoch')), 'Time': None,
            'Market Cap (Cr)': r.get('marketCap'), 'ECS Score': r.get('ecsScore'),
            'Guidance Move': r.get('guidanceMove'), 'PEAD Index': r.get('peadIndex'),
            'Forward Metrics Count': r.get('forwardCount') or len(fms),
            'Tags': ', '.join(tags) if isinstance(tags, list) else tags,
            'Summary': r.get('shortSummaryText'), 'Management Guidance': r.get('managementGuidance'),
            'Forward Metric 1': _fm(0), 'Forward Metric 2': _fm(1), 'Forward Metric 3': _fm(2),
            'ISIN': r.get('isin'), 'Recording Link': r.get('recordingLink'),
        })
    return pd.DataFrame(rows)

def _build_merged(res_df, conc_df):
    conc = conc_df[['ISIN','Date','ECS Score','Guidance Move','Tags','Summary','Management Guidance',
                    'Forward Metric 1','Forward Metric 2','Forward Metric 3','Recording Link']].rename(columns={
        'Date':'Concall Date','ECS Score':'ECS Score (Concall)','Guidance Move':'Guidance Move (Concall)','Summary':'Concall Summary'})
    m = res_df.merge(conc, on='ISIN', how='inner').rename(columns={'Date':'Result Date','ECS Score':'ECS Score (Results)'})
    cols = ['Symbol','Company','Sector','Result Date','Market Cap (Cr)','Revenue (Cr)','Rev YoY %',
            'EBITDA (Cr)','EBITDA YoY %','PAT (Cr)','PAT YoY %','OPM %','OPM YoY (bps)',
            'Result Verdict','Balance Sheet Health','AI Tag (PEAD Label)','PEAD Index',
            'ECS Score (Results)','ECS Score (Concall)','Price Move Since Result %',
            'Guidance Move (Concall)','Concall Date','Tags','Result Summary','Concall Summary',
            'Management Guidance','Forward Metric 1','Forward Metric 2','Forward Metric 3',
            'ISIN','PDF URL','Recording Link']
    for c in cols:
        if c not in m.columns: m[c] = None
    return m[cols]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out-dir', default='data', type=Path); a = ap.parse_args()
    a.out_dir.mkdir(exist_ok=True, parents=True)
    ck = os.environ.get('EQUISENSE_COOKIE')
    if not ck: sys.exit('EQUISENSE_COOKIE not set.')
    s = requests.Session()
    s.headers.update({'cookie': ck, 'User-Agent': UA, 'Accept':'application/json'})
    print('Fetching Results...')
    res_raw = _fetch_all(s, '/api/v1/discover/results/glance', '&sortCol=ecsScore&sortDir=desc')
    print('Fetching Concalls...')
    conc_raw = _fetch_all(s, '/api/v1/concalls')
    res_df = _norm_results(res_raw)
    conc_df = _norm_concalls(conc_raw)
    merged = _build_merged(res_df, conc_df)
    with pd.ExcelWriter(a.out_dir / 'EquiSense - Full Dataset (Results + Concalls).xlsx', engine='openpyxl') as w:
        merged.to_excel(w, sheet_name='Merged (Results+Concall)', index=False)
        res_df.to_excel(w, sheet_name='Results (All)', index=False)
        conc_df.to_excel(w, sheet_name='Concalls (All)', index=False)
    with pd.ExcelWriter(a.out_dir / 'EquiSense Concalls - All Data.xlsx', engine='openpyxl') as w:
        conc_df.to_excel(w, sheet_name='EquiSense Concalls', index=False)
    print(f'Wrote Excel: Merged {len(merged)}, Results {len(res_df)}, Concalls {len(conc_df)}')

if __name__ == '__main__': main()
