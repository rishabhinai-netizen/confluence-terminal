# Numbers for the v4 research report -> data/report4.json
import json
from swing import *
U = univ(); RS = rs_rank(126); prev = lambda d, k=1: d.shift(k)
R = {}
def st(D, T, nm): s = stats(D, T, nm); return {k: s[k] for k in ['name', 'cagr', 'dd', 'trades', 'win', 'avg', 'days', 'yearly', 'mar']}
TE = U & (C > prev(hi(55))); SE = U & (C > prev(hi(10)))
# 1) execution realism
ex = []
for nm, kw in [('Trend: sell at the signal close (needs acting before the close)', dict(entry=TE, score=RS, exit_sig=C < sma(50), min_hold=3, max_hold=250)),
               ('Trend: sell at the next close', dict(entry=TE, score=RS, exit_sig=C < sma(50), min_hold=3, max_hold=250, exit_lag=1)),
               ('Trend: stop order at yesterday\'s 50-day average (the rule)', dict(entry=TE, score=RS, dstop=sma(50), min_hold=3, max_hold=250)),
               ('Swing: sell at the signal close', dict(entry=SE, score=RS, exit_sig=C < ema(10), min_hold=2, max_hold=30)),
               ('Swing: sell at the next close (the rule)', dict(entry=SE, score=RS, exit_sig=C < ema(10), min_hold=2, max_hold=30, exit_lag=1)),
               ('Swing: stop order at yesterday\'s 10-day EMA', dict(entry=SE, score=RS, dstop=ema(10), min_hold=2, max_hold=30, exit_lag=1))]:
    D, T = simulate(**kw); ex.append(st(D, T, nm)); print(fmt(stats(D, T, nm)), flush=True)
R['exec'] = ex
# 2) robustness grid (executable exits)
grid = []
for n in (40, 55, 70, 100):
    for m in (40, 50, 70):
        D, T = simulate(U & (C > prev(hi(n))), RS, dstop=sma(m), min_hold=3, max_hold=250); s = st(D, T, f'Trend {n}-day breakout, stop {m}-day avg'); s['n'] = n; s['m'] = m; grid.append(s)
for n in (10, 20, 30):
    for m in (10, 20):
        D, T = simulate(U & (C > prev(hi(n))), RS, exit_sig=C < ema(m), min_hold=2, max_hold=30 if m == 10 else 60, exit_lag=1); s = st(D, T, f'Swing {n}-day breakout, exit {m}-day EMA'); s['n'] = n; s['m'] = m; grid.append(s)
R['grid'] = grid; print('grid done', flush=True)
# 3) gauge on/off for each book
gg = []
for nm, kw in [('Trend', dict(entry=TE, score=RS, dstop=sma(50), min_hold=3, max_hold=250)), ('Swing', dict(entry=SE, score=RS, exit_sig=C < ema(10), min_hold=2, max_hold=30, exit_lag=1))]:
    for reg in ('scale', None):
        D, T = simulate(regime=reg, **kw); gg.append(st(D, T, f'{nm} {"with gauge" if reg else "no gauge"}'))
R['gauge'] = gg
# 4) breakout analytics (signal level)
O = pd.read_pickle(rs2.S + '/data/out_d55_feat.pkl')
def tab(col, bins, labels, sub=None):
    X = O if sub is None else O[sub]; g = X.groupby(pd.cut(X[col], bins, labels=labels), observed=True).ret
    return [dict(bin=str(k), n=int(len(v)), avg=float(v.mean()), win=float((v > 0).mean())) for k, v in g]
R['brk'] = dict(
  rs=tab('rs', [0, .5, .7, .8, .9, .95, 1.0], ['bottom half', '50-70%', '70-80%', '80-90%', '90-95%', 'top 5%']),
  ext=tab('ext50', [-1, .05, .1, .15, .2, .3, 5], ['<5%', '5-10%', '10-15%', '15-20%', '20-30%', '>30%']),
  run=tab('run250', [-1, 0, .3, .6, 1, 2, 50], ['fell', '0-30%', '30-60%', '60-100%', '100-200%', '>200%']),
  mc=tab('mc', [0, 2000, 5000, 15000, 50000, 1e9], ['1-2k cr', '2-5k', '5-15k', '15-50k', '>50k']),
  res=tab('res', [-.01, .3, .5, .7, .9, 1.0], ['bottom 30%', '30-50%', '50-70%', '70-90%', 'top 10%'], O.yr >= 2023),
  vr=tab('vr', [0, 1, 1.5, 2, 3, 100], ['<1x', '1-1.5x', '1.5-2x', '2-3x', '>3x'], O.yr >= 2025),
  n=int(len(O)), avg=float(O.ret.mean()), win=float((O.ret > 0).mean()))
# 5) curves
BF = pd.read_pickle(rs2.S + '/data/books_final.pkl'); r = BF['r']
P = rs2.panel(); m = P['mret'].reindex(r.index).fillna(0)
cur = {}
for k in ['Trend', 'Swing', 'Results']: cur[k] = (1 + r[k]).cumprod()
cur['Equal-weight market'] = (1 + m).cumprod()
c23 = r.loc['2023':]; cur['All three (from 2023)'] = (1 + (c23['Trend'] + c23['Swing'] + c23['Results']) / 3).cumprod()
R['curves'] = {k: [[str(t.date()), round(float(x), 4)] for t, x in v.resample('W-FRI').last().dropna().items()] for k, v in cur.items()}
R['factor_ic'] = json.load(open(rs2.S + '/data/factor_ic.json'))
R['league'] = json.load(open(rs2.S + '/data/league4.json'))
R['comb'] = BF['comb']
json.dump(R, open(rs2.S + '/data/report4.json', 'w'), default=float)
print('ok')
