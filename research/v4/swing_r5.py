# Round 5: data add-ons at portfolio level, and the three books combined.
import json
from swing import *
U = univ(); RS = rs_rank(126); prev = lambda df, k=1: df.shift(k)
PER = {'design': ('2018-07-01', '2022-12-31'), 'valid': ('2023-01-01', '2024-12-31'), 'clean': ('2025-01-01', None), 'all': ('2018-07-01', None), 'since23': ('2023-01-01', None)}
EQ = {}
def run(name, keep=False, **kw):
    out = {}
    for per, (a, b) in PER.items():
        D, T = simulate(start=a, end=b, **kw); out[per] = stats(D, T, name)
        if keep and per == 'all': EQ[name] = D
    print(" ".join(f"{out[p]['cagr']*100:5.1f}/{out[p]['dd']*100:4.0f}" for p in ['design', 'valid', 'clean', 'since23']) + "  | " + fmt(out['all']), flush=True)
    return dict(name=name, **out)
R = []
D55 = U & (C > prev(hi(55))); X50 = C < sma(50)
ST = result_state('pr')
# guidance cut within the last 130 sessions
e = pd.read_pickle(rs2.S + '/data/ev_pit.pkl')
import glob
cc = {}
for f in glob.glob(rs2.S + '/data/es/concalls_Q*.jsonl'):
    for line in open(f):
        r = json.loads(line)
        if r.get('isin') and r.get('guidanceRevision') == 'CUT' and r.get('concallEventEpoch'): cc.setdefault(r['isin'], []).append(int(r['concallEventEpoch']))
CUT = pd.DataFrame(False, index=DATES, columns=ISINS)
for isin, eps in cc.items():
    if isin not in ISINS: continue
    j = ISINS.get_loc(isin)
    for ep in eps:
        i0 = DATES.searchsorted(pd.Timestamp(ep, unit='ms') + pd.Timedelta(hours=6), side='right')
        CUT.iloc[i0:i0 + 130, j] = True
R.append(run('Trend: D55, exit <50d', keep=True, entry=D55, score=RS, exit_sig=X50, min_hold=3, max_hold=250))
R.append(run('Trend + skip weak latest result (bottom 30%)', entry=D55 & ~(ST < 0.3), score=RS, exit_sig=X50, min_hold=3, max_hold=250))
R.append(run('Trend + skip recent guidance cut', entry=D55 & ~CUT, score=RS, exit_sig=X50, min_hold=3, max_hold=250))
R.append(run('Trend + both skips', keep=True, entry=D55 & ~(ST < 0.3) & ~CUT, score=RS, exit_sig=X50, min_hold=3, max_hold=250))
R.append(run('Trend, score = RS126 + 1y return', entry=D55, score=RS + ret(250).where(U).rank(axis=1, pct=True), exit_sig=X50, min_hold=3, max_hold=250))
R.append(run('Swing: D20, exit <EMA10', keep=True, entry=U & (C > prev(hi(20))), score=RS, exit_sig=C < ema(10), min_hold=2, max_hold=30))
R.append(run('Swing + both skips', keep=True, entry=U & (C > prev(hi(20))) & ~(ST < 0.3) & ~CUT, score=RS, exit_sig=C < ema(10), min_hold=2, max_hold=30))
ev = e[(e.pr >= 0.9) & (e.balanceSheetHealth != 'STRESSED')]
RE = pd.DataFrame(False, index=DATES, columns=ISINS)
for isin, ei in zip(ev['isin'], ev['ei']):
    if isin in ISINS: RE.iloc[int(ei):int(ei) + 10, ISINS.get_loc(isin)] = True
R.append(run('Results Leaders (v3): top 10%, hold 60', keep=True, entry=RE & ~CUT, score=result_state('score'), max_hold=60, slots=15))
pd.to_pickle(EQ, rs2.S + '/data/books_eq.pkl'); pd.to_pickle(CUT, rs2.S + '/data/cut_mask.pkl')
# combined books (daily rebalanced capital split)
r = pd.DataFrame({k: v.r for k, v in EQ.items()}).fillna(0)
print(r.loc['2023':].corr().round(2))
def comb(w, start):
    x = (r.loc[start:] * pd.Series(w)).sum(axis=1); eq = (1 + x).cumprod(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    y = eq.resample('YE').last(); prevy = np.r_[1.0, y.values[:-1]]
    return dict(w=w, start=start, cagr=eq.iloc[-1] ** (1 / yrs) - 1, dd=(eq / eq.cummax() - 1).min(), yearly={str(k.year): v for k, v in zip(y.index, y.values / prevy - 1)})
for w in [{'Trend + both skips': 1.0}, {'Trend + both skips': .5, 'Swing + both skips': .5}, {'Trend + both skips': .5, 'Results Leaders (v3): top 10%, hold 60': .5},
          {'Trend + both skips': .4, 'Swing + both skips': .3, 'Results Leaders (v3): top 10%, hold 60': .3}]:
    c = comb(w, '2023-01-01'); print(f"{c['cagr']*100:5.1f}% dd {c['dd']*100:5.1f}", {k: round(v * 100) for k, v in c['yearly'].items()}, w)
json.dump(R, open(rs2.S + '/data/swing_r5.json', 'w'), indent=1, default=float)
