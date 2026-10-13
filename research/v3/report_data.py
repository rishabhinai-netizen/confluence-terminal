# Collect every number the v3 research report shows into data/report.json
import league as L, strat, sim2, rs2, numpy as np, pandas as pd, json, glob, os
S = L.S; e = L.e; v = strat.exposure('vote3')
R = {}
# 1) decile gradient of the composite (event level, 60-session excess return vs equal-weight universe, entry next close)
d = e[e.pr.notna()].copy(); d['dec'] = np.minimum((d.pr * 10).astype(int), 9) + 1
g = d.groupby('dec').agg(n=('x60_l1', 'count'), med=('x60_l1', 'median'), mean=('x60_l1', lambda s: s.clip(-1, 3).mean()), hit=('x60_l1', lambda s: (s > 0).mean()),
                         rmed=('r60_l1', 'median'))
R['deciles'] = [dict(dec=int(k), **{c: float(g.loc[k, c]) for c in g.columns}) for k in g.index]
# by year for top decile vs all
d['yr'] = d.ts.dt.year
R['top_by_year'] = [dict(yr=int(y), top=float(gg[gg.dec == 10].x60_l1.median()), all=float(gg.x60_l1.median()), n_top=int((gg.dec == 10).sum()))
                    for y, gg in d.groupby('yr')]
# 2) components alone
comp = {}
for k, col in [('Growth only (top 10%)', 'g_growth'), ('Trend only (top 10%)', 'g_trend'), ('Reaction only (top 10%)', 'g_react')]:
    m = e[col].values >= L.prev_q(col, 0.9)
    comp[k] = L.run_pool(k, m, n=12)
    print(k, comp[k]['cagr'], comp[k]['dd'], flush=True)
R['components'] = list(comp.values())
# 3) curves (weekly): model ranked with gauge, model ranked without gauge, baseline random-median with gauge, EW universe, BSE 500, Smallcap 250
m = L.pools['Composite top 10% (growth x2 + trend + reaction)']
eq = {}
eq['Model (top 10%, gauge)'] = sim2.run(L.signals(m, e.score.values), e, start='2023-01-01', exposure=v, regime_mode='scale')['eq'].equity
eq['Model without gauge'] = sim2.run(L.signals(m, e.score.values), e, start='2023-01-01', exposure=None, regime_mode='scale')['eq'].equity
rng = np.random.default_rng(5); base = []
allm = L.pools['All tradeable results (baseline)']
for k in range(12):
    base.append(sim2.run(L.signals(allm, rng.random(len(e))), e, start='2023-01-01', exposure=v, regime_mode='scale')['eq'].equity)
eq['Any result, random picks (median of 12)'] = pd.concat(base, axis=1).median(axis=1)
P = rs2.panel(); mk = P['mkt']; mk = mk[mk.index >= '2023-01-01']; eq['Equal-weight universe'] = mk / mk.iloc[0]
ix = json.load(open(f'{S}/data/index_5y.json'))
for grp in ix['groups']:
    if grp['name'] in ('BSE 500', 'Nifty Smallcap 250', 'BSE SmallCap', 'Nifty 50'):
        s = pd.Series({pd.Timestamp(b[0]): b[4] for b in grp['bars']}); s = s[s.index >= '2022-12-26']; eq[grp['name']] = s / s.iloc[0]
W = {}
for k, s in eq.items():
    w = s.resample('W-FRI').last().dropna(); w = w / w.iloc[0]
    W[k] = [[str(t.date()), round(float(x), 4)] for t, x in w.items()]
R['curves'] = W
R['index_names'] = [g_['name'] for g_ in ix['groups']]
def yr(s):
    y = s.resample('YE').last(); p = pd.concat([pd.Series([s.iloc[0]]), y.iloc[:-1]]).values; return {str(k.year): float(a / b - 1) for k, a, b in zip(y.index, y.values, p)}
R['curve_stats'] = {k: dict(cagr=float(s.iloc[-1] ** (365.25 / (s.index[-1] - s.index[0]).days) - 1), dd=float((s / s.cummax() - 1).min()), yearly=yr(s), end=str(s.index[-1].date())) for k, s in eq.items()}
# 4) census
cen = {}
cnt = lambda pat: sum(sum(1 for _ in open(f)) for f in glob.glob(pat))
cen['results_rows'] = cnt(f'{S}/data/es/results_Q*.jsonl'); cen['concall_rows'] = cnt(f'{S}/data/es/concalls_Q*.jsonl')
cen['filings_rows'] = {os.path.basename(f)[8:-6]: sum(1 for _ in open(f)) for f in glob.glob(f'{S}/data/es/filings_*.jsonl')}
se = pd.read_pickle(f'{S}/data/smart_events.pkl'); cen['smart_rows'] = len(se); cen['smart_from'] = str(pd.to_datetime(se.dealDate).min().date())
cen['events_scored'] = int(e.pr.notna().sum()); cen['events_all'] = len(rs2.results_events())
cen['panel_days'] = len(P['dates']); cen['panel_isins'] = P['c'].shape[1]; cen['panel_from'] = str(P['dates'][0].date())
cen['ss_holdings_dates'] = len({json.loads(l).get('_d') or json.loads(l).get('d') for l in open(f'{S}/data/ssp/Holdings.jsonl')})
R['census'] = cen
R['league'] = json.load(open(f'{S}/data/league.json')); R['gauge'] = json.load(open(f'{S}/data/gauge_test.json'))
if os.path.exists(f'{S}/data/exit_test.json'): R['exits'] = json.load(open(f'{S}/data/exit_test.json'))
json.dump(R, open(f'{S}/data/report.json', 'w'))
print('ok', R['curve_stats'])
