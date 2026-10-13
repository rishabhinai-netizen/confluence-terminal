# Round 3: trend-following family in depth + results-triggered entries with trend exits + Clenow rotation.
import json
from swing import *
U = univ(); T200 = C > sma(200); UP = sma(50) > sma(200); RS = rs_rank(126)
prev = lambda df, k=1: df.shift(k)
VS = (vol(20).median(axis=1).values[:, None] / vol(20)).clip(upper=1.0)     # volatility sizing: shrink volatile names only
def run(name, **kw):
    out = {}
    for per, (a, b) in {'design': ('2018-07-01', '2022-12-31'), 'valid': ('2023-01-01', None), 'all': ('2018-07-01', None)}.items():
        D, T = simulate(start=a, end=b, **kw); out[per] = stats(D, T, name)
    print(f"{out['design']['cagr']*100:6.1f}/{out['design']['dd']*100:5.0f}  {out['valid']['cagr']*100:6.1f}/{out['valid']['dd']*100:5.0f}  | " + fmt(out['all']), flush=True)
    return dict(name=name, **out)
R = []
d20 = U & (C > prev(hi(20))); d55 = U & (C > prev(hi(55)))
base = dict(score=RS, stop=None, exit_sig=C < sma(50), min_hold=3, max_hold=250)
R.append(run('D20 / exit<50d / no stop', entry=d20, **base))
R.append(run('D55 / exit<50d / no stop', entry=d55, **base))
R.append(run('D55 / exit lo20 / no stop', entry=d55, score=RS, exit_sig=C < prev(lo(20)), max_hold=250))
R.append(run('D55 / exit lo20 / stop 20%', entry=d55, score=RS, stop=0.20, exit_sig=C < prev(lo(20)), max_hold=250))
R.append(run('D20 / exit<50d / vol sizing', entry=d20, size_df=VS, **base))
R.append(run('D55 / exit lo20 / vol sizing', entry=d55, score=RS, exit_sig=C < prev(lo(20)), max_hold=250, size_df=VS))
R.append(run('D20 / exit<50d / 15 slots', entry=d20, slots=15, **base))
R.append(run('D20 / exit<50d / RS63', entry=d20, score=rs_rank(63), stop=None, exit_sig=C < sma(50), min_hold=3, max_hold=250))
R.append(run('D20 / exit<50d / RS252', entry=d20, score=rs_rank(250), stop=None, exit_sig=C < sma(50), min_hold=3, max_hold=250))
CL = clenow(90)
R.append(run('D20 / exit<50d / Clenow rank', entry=d20, score=CL, stop=None, exit_sig=C < sma(50), min_hold=3, max_hold=250))
# Clenow rotation: weekly, top 30 by momentum above 100-day avg, exit when out of top 20% or below 100-day avg
wk = pd.Series(DATES.dayofweek == 2, index=DATES)
clr = CL.where(U).rank(axis=1, pct=True)
ent = U & (C > sma(100)) & (clr >= 0.97) & pd.DataFrame(np.repeat(wk.values[:, None], len(ISINS), 1), index=DATES, columns=ISINS)
ext = ((clr < 0.8) | (C < sma(100))) & pd.DataFrame(np.repeat(wk.values[:, None], len(ISINS), 1), index=DATES, columns=ISINS)
R.append(run('Clenow rotation weekly (top 3% in, out <80% or <100d)', entry=ent, score=CL, exit_sig=ext, max_hold=500, slots=15))
# results-triggered entries with trend exits (2023+ meaningful)
e = pd.read_pickle(rs2.S + '/data/ev_pit.pkl'); e = e[(e.pr >= 0.9) & (e.balanceSheetHealth != 'STRESSED')]
RE = pd.DataFrame(False, index=DATES, columns=ISINS)
for isin, ei in zip(e['isin'], e['ei']):
    if isin in ISINS:
        j = ISINS.get_loc(isin); RE.iloc[int(ei):int(ei) + 10, j] = True
SC = result_state('score')
R.append(run('Results top10% / hold 60 (v3)', entry=RE, score=SC, max_hold=60, slots=15))
R.append(run('Results top10% / exit<50d', entry=RE, score=SC, exit_sig=C < sma(50), min_hold=3, max_hold=250, slots=15))
R.append(run('Results top10% / exit lo20', entry=RE, score=SC, exit_sig=C < prev(lo(20)), max_hold=250, slots=15))
R.append(run('Results top10% AND D20 breakout within window', entry=RE & (C >= prev(hi(20))), score=SC, exit_sig=C < sma(50), min_hold=3, max_hold=250, slots=15))
json.dump(R, open(rs2.S + '/data/swing_r3.json', 'w'), indent=1)
