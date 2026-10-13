import league as L, strat, sim2, numpy as np, json
m = L.pools['Composite top 10% (growth x2 + trend + reaction)']
v = strat.exposure('vote3')
out = []
def go(name, **kw):
    rng = np.random.default_rng(11); res = []
    for k in range(12):
        R = sim2.run(L.signals(m, rng.random(len(L.e))), L.e, start='2023-01-01', exposure=v, regime_mode='scale', **kw)
        res.append(L.stats(R['eq'], '2023-01-01'))
    r = dict(name=name, cagr=float(np.median([o['cagr'] for o in res])), dd=float(np.median([o['dd'] for o in res])),
             yearly={y: float(np.median([o['yearly'][y] for o in res])) for y in res[0]['yearly']})
    out.append(r); print(f"{r['cagr']*100:6.1f} dd {r['dd']*100:6.1f}", {a: round(b*100,1) for a,b in r['yearly'].items()}, name, flush=True)
go('Hold 20 sessions', hold=20)
go('Hold 40 sessions', hold=40)
go('Hold 60 sessions (model)', hold=60)
go('Hold 120 sessions', hold=120)
go('Exit on close below 50-day average', exit_mode='sma', sma_n=50, min_days=10)
go('Hold while next result also qualifies', exit_mode='confirm', keep_pr=0.5)
json.dump(out, open(L.S + '/data/exit_test.json', 'w'), indent=1)
