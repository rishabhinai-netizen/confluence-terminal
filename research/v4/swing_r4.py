# Round 4: robustness grid around the leading trend rule + shorter swing variants + fundamental tie-breaks.
import json
from swing import *
U = univ(); RS = rs_rank(126)
prev = lambda df, k=1: df.shift(k)
PER = {'design': ('2018-07-01', '2022-12-31'), 'valid': ('2023-01-01', '2024-12-31'), 'clean': ('2025-01-01', None), 'all': ('2018-07-01', None)}
def run(name, **kw):
    out = {}
    for per, (a, b) in PER.items():
        D, T = simulate(start=a, end=b, **kw); out[per] = stats(D, T, name)
    print(" ".join(f"{out[p]['cagr']*100:5.1f}/{out[p]['dd']*100:4.0f}" for p in ['design', 'valid', 'clean']) + "  | " + fmt(out['all']), flush=True)
    return dict(name=name, **out)
R = []
for n in (40, 55, 70, 100, 250):
    for ex in (('sma50', C < sma(50)), ('sma100', C < sma(100)), ('ema30', C < ema(30))):
        R.append(run(f'D{n} exit {ex[0]}', entry=U & (C > prev(hi(n))), score=RS, exit_sig=ex[1], min_hold=3, max_hold=250))
for sl in (6, 8, 12, 15):
    R.append(run(f'D55 exit sma50 slots {sl}', entry=U & (C > prev(hi(55))), score=RS, exit_sig=C < sma(50), min_hold=3, max_hold=250, slots=sl))
R.append(run('D55 exit sma50 RS200', entry=U & (C > prev(hi(55))), score=rs_rank(200), exit_sig=C < sma(50), min_hold=3, max_hold=250))
R.append(run('D55 exit sma50 no gauge', entry=U & (C > prev(hi(55))), score=RS, exit_sig=C < sma(50), min_hold=3, max_hold=250, regime=None))
R.append(run('D55 exit sma50 cost 0.5%', entry=U & (C > prev(hi(55))), score=RS, exit_sig=C < sma(50), min_hold=3, max_hold=250, cost=0.005))
R.append(run('D55 exit sma50 same close', entry=U & (C > prev(hi(55))), score=RS, exit_sig=C < sma(50), min_hold=3, max_hold=250, lag=0))
# shorter swing variants (1-3 weeks)
R.append(run('Swing: D20, exit close<10-day low', entry=U & (C > prev(hi(20))), score=RS, exit_sig=C < prev(lo(10)), max_hold=30))
R.append(run('Swing: D20, exit close<EMA10', entry=U & (C > prev(hi(20))), score=RS, exit_sig=C < ema(10), min_hold=2, max_hold=30))
R.append(run('Swing: D20, +15% target / -7% stop / 15 days', entry=U & (C > prev(hi(20))), score=RS, stop=0.07, target=0.15, max_hold=15))
R.append(run('Swing: D20 in RS top 10%, exit<EMA10', entry=U & (C > prev(hi(20))) & (RS >= 0.9), score=RS, exit_sig=C < ema(10), min_hold=2, max_hold=30))
json.dump(R, open(rs2.S + '/data/swing_r4.json', 'w'), indent=1)
