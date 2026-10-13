import league as L, strat, numpy as np, pandas as pd, json
m = L.pools['Composite top 10% (growth x2 + trend + reaction)']
v = strat.exposure('vote3')
variants = {'no gauge': None, 'scale by gauge (0..1)': v, 'skip only when gauge = 0': (v > 0).astype(float),
            'skip when gauge <= 1/3': (v > 0.34).astype(float)}
out = []
for k, ex in variants.items():
    for ranked in (False, True):
        r = L.run_pool(k + (' | ranked' if ranked else ' | random order'), m, ranked=ranked, expo=ex, n=20)
        out.append(r); print(f"{r['cagr']*100:6.1f} dd {r['dd']*100:6.1f} p10 {r['cagr_p10']*100:5.1f}", {a: round(b*100,1) for a,b in r['yearly'].items()}, r['name'], flush=True)
json.dump(out, open(L.S + '/data/gauge_test.json', 'w'), indent=1)
