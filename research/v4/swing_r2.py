# Round 2: breakouts in depth. Design 2018-07..2022-12, validation 2023..2026-10 reported separately.
import json, itertools
from swing import *
U = univ(); U2 = univ(2000); T200 = C > sma(200); UP = sma(50) > sma(200); RS = rs_rank(126)
prev = lambda df, k=1: df.shift(k)
ST = result_state('pr')          # composite results rank (2023+)
def run(name, **kw):
    out = {}
    for per, (a, b) in {'design': ('2018-07-01', '2022-12-31'), 'valid': ('2023-01-01', None), 'all': ('2018-07-01', None)}.items():
        D, T = simulate(start=a, end=b, **kw); out[per] = stats(D, T, name)
    print(f"{out['design']['cagr']*100:6.1f}/{out['design']['dd']*100:5.0f}  {out['valid']['cagr']*100:6.1f}/{out['valid']['dd']*100:5.0f}  | " + fmt(out['all']), flush=True)
    return dict(name=name, **out)
R = []
don = U & (C > prev(hi(20)))
w52 = U & (C > prev(hi(250)))
for lag in (1,):
    R.append(run('Donchian20 base', entry=don, score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
    for ex_name, ex in [('lo20', C < prev(lo(20))), ('ema20', C < ema(20)), ('sma50', C < sma(50))]:
        R.append(run(f'Donchian20 exit {ex_name}', entry=don, score=RS, stop=0.10, exit_sig=ex, min_hold=3, max_hold=120, lag=lag))
    for st in (0.07, 0.15, None):
        R.append(run(f'Donchian20 stop {st}', entry=don, score=RS, stop=st, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
    R.append(run('Donchian20 trail 15%', entry=don, score=RS, stop=0.10, trail=0.15, max_hold=120, lag=lag))
    R.append(run('Donchian20 RS>=0.8', entry=don & (RS >= 0.8), score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
    R.append(run('Donchian20 trend (>200, 50>200)', entry=don & T200 & UP, score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
    R.append(run('Donchian20 mcap>=2000', entry=don & U2, score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
    R.append(run('Donchian20 no gauge', entry=don, score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag, regime=None))
    R.append(run('Donchian20 block <0.5', entry=don, score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag, regime='block'))
    R.append(run('Donchian20 20 slots', entry=don, score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag, slots=20))
    R.append(run('Donchian20 score=-vol (calm first)', entry=don, score=-vol(20), stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
    R.append(run('Donchian20 score=ret20 (strongest burst)', entry=don, score=ret(20), stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
    R.append(run('Donchian55 exit lo20 (Turtle 2)', entry=U & (C > prev(hi(55))), score=RS, stop=0.12, exit_sig=C < prev(lo(20)), max_hold=120, lag=lag))
    R.append(run('52w high exit lo10', entry=w52, score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
    R.append(run('52w high exit sma50, hold 120', entry=w52, score=RS, stop=0.10, exit_sig=C < sma(50), min_hold=3, max_hold=120, lag=lag))
    # results state filters (meaningful from 2023)
    R.append(run('Donchian20 + latest result top 30%', entry=don & (ST >= 0.7), score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
    R.append(run('Donchian20 + latest result top 50%', entry=don & (ST >= 0.5), score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
    R.append(run('Donchian20 + latest result bottom 50%', entry=don & (ST < 0.5), score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
    R.append(run('Donchian20 score = results rank', entry=don & ST.notna(), score=ST, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60, lag=lag))
json.dump(R, open(rs2.S + '/data/swing_r2.json', 'w'), indent=1)
