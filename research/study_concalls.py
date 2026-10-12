# Event study: EquiSense concall attributes -> forward excess returns (entry: close of first session after the call).
import json, glob, sys, numpy as np, pandas as pd
sys.path.insert(0, '' + os.path.dirname(os.path.abspath(__file__)) + '')
import rs
S = rs.S
KEEP = ['id', 'isin', 'symbol', 'companySector', 'concallEventEpoch', 'quarter', 'year', 'managementTone', 'guidanceRevision',
        'guidanceDelivery', 'convictionLevel', 'analystSentiment', 'managementCandor', 'earningsQuality', 'turnaround',
        'storyType', 'peadIndex', 'forwardCount', 'status', 'callType', 'callOccasion', 'tags']
rows = []
for f in sorted(glob.glob(f'{S}/data/es/concalls_Q*.jsonl')):
    for l in open(f):
        r = json.loads(l); rows.append({k: r.get(k) for k in KEEP})
df = pd.DataFrame(rows)
df = df[(df['status'] == 'COMPLETED') & df['concallEventEpoch'].notna()].copy()
df['ts'] = pd.to_datetime(df['concallEventEpoch'], unit='ms', utc=True).dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
df['qtag'] = 'Q' + df['quarter'].astype(str) + 'FY' + df['year'].astype(str)
P = rs.panel()
df = df[df['isin'].isin(P['c'].columns)].copy()
df = rs.attach(df, horizons=(5, 20, 40, 60))
df.to_pickle(f'{S}/data/es_concall_events.pkl')
print('events', len(df), df.groupby('qtag').size().to_dict())
base = {h: (round(df[f'x{h}'].dropna().median() * 100, 2), round((df[f'x{h}'].dropna() > 0).mean() * 100, 1)) for h in (20, 40, 60)}
print('baseline (median excess %, hit %):', base)
pd.set_option('display.width', 200)
for col in ['guidanceRevision', 'guidanceDelivery', 'managementTone', 'convictionLevel', 'analystSentiment',
            'managementCandor', 'earningsQuality', 'turnaround', 'storyType']:
    print('\n==', col, df[col].isna().mean().round(2), 'missing')
    for h in (20, 60):
        t = rs.summarize(df, col, h, min_n=25)
        if len(t): print(f'  h={h}'); print(t.to_string(index=False))
