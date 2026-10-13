# Cross-sectional factor tests: month-end cross-sections (2025-05 -> 2026-08), forward 20/60-session return vs equal-weight universe.
import sys, json
from ss_feat import *
U = univ()
ME = [d for i, d in enumerate(DATES) if d >= pd.Timestamp('2025-05-01') and (i == len(DATES) - 1 or DATES[i + 1].month != d.month)]
def fwd(h):
    return C.shift(-h - 1) / C.shift(-1) - 1    # buy next close, hold h sessions
def ic(M, name, hs=(20, 60), sign=1):
    out = dict(name=name)
    for h in hs:
        F = fwd(h); ics = []; spreads = []
        for d in ME:
            i = DATES.get_loc(d)
            x = M.iloc[i] if isinstance(M, pd.DataFrame) else None
            y = F.iloc[i]; ok = U.iloc[i] & x.notna() & y.notna()
            if ok.sum() < 100: continue
            xs, ys = x[ok] * sign, y[ok] - y[ok].mean()
            ics.append(xs.rank().corr(ys.rank()))
            q = pd.qcut(xs.rank(method='first'), 5, labels=False)
            spreads.append(ys[q == 4].mean() - ys[q == 0].mean())
        if ics:
            a = np.array(ics); out[f'ic{h}'] = a.mean(); out[f't{h}'] = a.mean() / (a.std(ddof=1) / np.sqrt(len(a))) if len(a) > 2 else np.nan
            out[f'q5q1_{h}'] = float(np.mean(spreads)); out['n'] = len(a)
    print(f"{name:55s} " + " ".join(f"IC{h} {out.get(f'ic{h}', np.nan):+.3f} (t {out.get(f't{h}', np.nan):+.1f}) Q5-Q1 {out.get(f'q5q1_{h}', np.nan)*100:+.1f}%" for h in hs) + f"  n={out.get('n')}", flush=True)
    return out
if __name__ == '__main__':
    R = []
    R.append(ic(rs_rank(126), 'Price: 6-month relative strength'))
    R.append(ic(result_state('pr'), 'EquiSense: latest result composite rank'))
    R.append(ic(C / hi(250) - 1, 'Price: distance from 52-week high'))
    for fld in ['Change In FII Holdings Latest Quarter', 'Change In DII Holdings Latest Quarter', 'Change In Promoter Holdings Latest Quarter',
                'Change In Retail Holdings Latest Quarter', 'Change In FII Holdings 1 Year', 'Change In DII Holdings 1 Year', 'Promoter Holdings', 'FII Holdings', 'DII Holdings']:
        M = panel('Holdings.jsonl', fld); R.append(ic(M, 'Holdings: ' + fld))
    for f, flds in [('v4_Scores.jsonl', ['Score', 'Score Change 1M']), ('v4_Ratios.jsonl', ['ROCE', 'ROE', 'OPM', 'NPM', 'Debt To Equity']),
                    ('v4_Valuation.jsonl', ['Price To Earnings', 'Price To Sales']), ('v4_Cash_Flow.jsonl', ['Operating Cash Flow', 'Free Cash Flow'])]:
        for fld in flds:
            M = panel(f, fld, max_age_days=120)
            if M is not None and M.notna().sum().sum() > 1000: R.append(ic(M, f'{f[3:-6]}: {fld}'))
    json.dump(R, open(rs2.S + '/data/factor_ic.json', 'w'), indent=1, default=float)
