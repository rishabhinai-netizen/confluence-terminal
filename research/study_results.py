# Event study: EquiSense quarterly results -> forward excess returns.
import json, glob, sys, numpy as np, pandas as pd
sys.path.insert(0, '' + os.path.dirname(os.path.abspath(__file__)) + '')
import rs
S = rs.S
rows = []
for f in sorted(glob.glob(f'{S}/data/es/results_Q*.jsonl')):
    for l in open(f): rows.append(json.loads(l))
df = pd.DataFrame(rows)
df = df[df['status'] == 'COMPLETED'].copy()
df['ts'] = pd.to_datetime(df['resultAnnouncementEpoch'], unit='ms', utc=True).dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
df['qtag'] = 'Q' + df['quarter'].astype(str) + 'FY' + df['fy'].astype(str)
P = rs.panel()
df = df[df['isin'].isin(P['c'].columns)].copy()
df = rs.attach(df, horizons=(1, 5, 20, 40, 60))
# day-0 reaction: close of entry day vs close before announcement (known at entry, so usable as a filter)
def react(isin, ts):
    c = P['c'][isin].values; i = rs.entry_index(ts)
    if i < 1 or i >= len(c): return np.nan
    j = i - 1
    while j > 0 and not np.isfinite(c[j]): j -= 1
    pre = c[j - 1] if j >= 1 else np.nan  # close of the session before the announcement day
    return c[i] / pre - 1 if np.isfinite(pre) and pre > 0 else np.nan
df['react'] = [react(i, t) for i, t in zip(df['isin'], df['ts'])]
df.to_pickle(f'{S}/data/es_results_events.pkl')
print('events', len(df), df.groupby('qtag').size().to_dict())
pd.set_option('display.width', 200)
for col in ['peadLabel', 'resultVerdict', 'balanceSheetHealth', 'peadIndex', 'driftConfidence']:
    print('\n==', col)
    for h in (20, 60):
        t = rs.summarize(df, col, h)
        print(f'  h={h}'); print(t.to_string(index=False))
