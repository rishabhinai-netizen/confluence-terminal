# Event studies for the sources with only ~1 year of history (too short for a strategy test).
import rs2, numpy as np, pandas as pd, json
P = rs2.panel(); C = P['c']; dates = P['dates']; cv = C.values; mk = P['mkt'].values; col = {k: i for i, k in enumerate(C.columns)}
def fwd(isins, ts, h):
    out = []
    for i, t in zip(isins, ts):
        if i not in col: out.append(np.nan); continue
        j = int(dates.searchsorted(pd.Timestamp(t).normalize(), side='right'))   # first close after the filing day
        if j + h >= len(dates): out.append(np.nan); continue
        a, b = cv[j, col[i]], cv[j + h, col[i]]
        out.append(b / a - 1 - (mk[j + h] / mk[j] - 1) if np.isfinite(a) and np.isfinite(b) and a > 0 else np.nan)
    return np.array(out)
S = rs2.S; res = {}
o = pd.DataFrame([json.loads(l) for l in open(f'{S}/data/es/filings_orders.jsonl')])
o['ts'] = pd.to_datetime(o.filedAt, unit='ms') + pd.Timedelta(hours=5, minutes=30)
o['x20'] = fwd(o['isin'], o.ts, 20); o['x5'] = fwd(o['isin'], o.ts, 5)
print(o.impactDirection.value_counts().to_dict(), o.impactScore.describe().to_dict())
def summ(d, name):
    x = d.x20.dropna(); r = dict(name=name, n=int(len(x)), med=float(x.median()) if len(x) else None, mean=float(x.clip(-1, 2).mean()) if len(x) else None, hit=float((x > 0).mean()) if len(x) else None)
    print(r); return r
res['orders'] = [summ(o, 'All order filings'), summ(o[o.impactScore >= o.impactScore.quantile(0.9)], 'Order filings, top 10% impact score'),
                 summ(o[(o.impactDirection.astype(str).str.upper().str.startswith('POS'))], 'Order filings marked positive')]
s = pd.read_pickle(f'{S}/data/smart_events.pkl')
s['x20b'] = fwd(s['isin'], pd.to_datetime(s.disclosureDate.fillna(s.dealDate)), 20); s['x20'] = s.x20b
res['smart'] = [summ(s, 'All smart-money deals'),
  summ(s[(s.source == 'INSIDER') & (s.dealType.str.upper().str.contains('BUY')) & s.promoter], 'Promoter buying (insider filings)'),
  summ(s[(s.source == 'INSIDER') & (s.dealType.str.upper().str.contains('SELL')) & ~s.promoter], 'Non-promoter insider selling'),
  summ(s[(s.source.isin(['BULK', 'BLOCK'])) & (s.dealType.str.upper().str.contains('BUY')) & (s.pct_mcap >= 0.5)], 'Bulk/block buys >= 0.5% of market cap')]
res['range'] = dict(orders=[str(o.ts.min().date()), str(o.ts.max().date())], smart=[str(pd.to_datetime(s.dealDate).min().date()), str(pd.to_datetime(s.dealDate).max().date())])
json.dump(res, open(f'{S}/data/short_events.json', 'w'), indent=1)
