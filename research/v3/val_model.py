# Python reference run of the model portfolio over the SQL model window, for cross-checking ct_model_*.
import pandas as pd, numpy as np, sim2, strat, rs2, sys
e = pd.read_pickle('../data/ev_pit.pkl')
dates = sim2.dates
ok = (e.pr >= 0.9) & (e.balanceSheetHealth != 'STRESSED')
s = e[ok]
rows = []
for isin, ei, sc in zip(s['isin'], s['ei'], s['score']):
    for k in range(10):
        j = int(ei) + k
        if j < len(dates): rows.append((isin, dates[j], sc))
sig = pd.DataFrame(rows, columns=['isin', 'd', 'score'])
ex = strat.exposure('vote3')
start = sys.argv[1] if len(sys.argv) > 1 else '2025-01-01'
R = sim2.run(sig, e, start=start, exposure=ex, regime_mode='scale')
D = R['eq']
print('end', round(D.equity.iloc[-1], 4), D.index[-1].date(), 'dd', round((D.equity / D.equity.cummax() - 1).min(), 4))
print(D.equity.resample('YE').last().round(4).to_dict())
T = R['trades']; print('trades', len(T), round(T.ret.mean(), 4), round((T.ret > 0).mean(), 3))
print('open', sorted(R['pos'].keys()))
