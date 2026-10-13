# Final three books (fixed rules) and their combinations; saves daily returns for the report.
import json
from swing import *
U = univ(); RS = rs_rank(126); prev = lambda d, k=1: d.shift(k)
CUT = pd.read_pickle(rs2.S + '/data/cut_mask.pkl')
e = pd.read_pickle(rs2.S + '/data/ev_pit.pkl'); ev = e[(e.pr >= 0.9) & (e.balanceSheetHealth != 'STRESSED')]
RE = pd.DataFrame(False, index=DATES, columns=ISINS)
for isin, ei in zip(ev['isin'], ev['ei']):
    if isin in ISINS: RE.iloc[int(ei):int(ei) + 10, ISINS.get_loc(isin)] = True
G2 = pd.DataFrame(np.repeat((GAUGE >= 0.6).values[:, None], len(ISINS), 1), index=DATES, columns=ISINS)
BOOKS = {
  'Trend': dict(entry=U & (C > prev(hi(55))), score=RS, dstop=sma(50), min_hold=3, max_hold=250),
  'Swing': dict(entry=U & (C > prev(hi(10))), score=RS, exit_sig=C < ema(10), min_hold=2, max_hold=30, exit_lag=1),
  'Results': dict(entry=RE & ~CUT, score=result_state('score'), max_hold=60, slots=15),
}
out = {}; RR = {}; TT = {}
for k, kw in BOOKS.items():
    D, T = simulate(start='2018-07-01', **kw); RR[k] = D.r; TT[k] = T
    out[k] = {'all': stats(D, T, k)}
    for per, (a, b) in {'design': ('2018-07-01', '2022-12-31'), 'since23': ('2023-01-01', None), 'clean': ('2025-01-01', None)}.items():
        D2, T2 = simulate(start=a, end=b, **kw); out[k][per] = stats(D2, T2, k)
    print(fmt(out[k]['all']), '| since23', round(out[k]['since23']['cagr'] * 100, 1), round(out[k]['since23']['dd'] * 100, 1))
r = pd.DataFrame(RR).fillna(0)
def comb(w, start):
    x = (r.loc[start:] * pd.Series(w)).sum(axis=1); eq = (1 + x).cumprod(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    y = eq.resample('YE').last(); pv = np.r_[1.0, y.values[:-1]]
    return dict(w=w, start=start, cagr=float(eq.iloc[-1] ** (1 / yrs) - 1), dd=float((eq / eq.cummax() - 1).min()), yearly={str(k.year): float(a / b - 1) for k, a, b in zip(y.index, y.values, pv)}, eq=eq)
C1 = {}
for nm, w in {'Trend 50 / Swing 25 / Results 25': {'Trend': .5, 'Swing': .25, 'Results': .25}, 'Trend 50 / Swing 50': {'Trend': .5, 'Swing': .5},
              'Equal thirds': {'Trend': 1 / 3, 'Swing': 1 / 3, 'Results': 1 / 3}, 'Trend only': {'Trend': 1.0}}.items():
    for st in ('2018-07-01', '2023-01-01'):
        c = comb(w, st); C1[f'{nm}|{st}'] = c
        print(f"{nm:35s} from {st}: {c['cagr']*100:5.1f}% dd {c['dd']*100:5.1f}", {k: round(v * 100) for k, v in c['yearly'].items()})
print(r.loc['2023':].corr().round(2))
pd.to_pickle(dict(r=r, trades=TT, stats=out, comb={k: {kk: vv for kk, vv in v.items() if kk != 'eq'} for k, v in C1.items()}), rs2.S + '/data/books_final.pkl')
