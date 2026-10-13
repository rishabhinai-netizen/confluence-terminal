# Round 6: ranking with every factor that showed cross-sectional edge (RS, 52-week-high proximity, latest result rank) + continuous rank book.
import json
from swing import *
U = univ(); RS = rs_rank(126); prev = lambda df, k=1: df.shift(k)
PER = {'design': ('2018-07-01', '2022-12-31'), 'valid': ('2023-01-01', '2024-12-31'), 'clean': ('2025-01-01', None), 'all': ('2018-07-01', None), 'since23': ('2023-01-01', None)}
def run(name, **kw):
    out = {}
    for per, (a, b) in PER.items():
        D, T = simulate(start=a, end=b, **kw); out[per] = stats(D, T, name)
    print(" ".join(f"{out[p]['cagr']*100:5.1f}/{out[p]['dd']*100:4.0f}" for p in ['design', 'valid', 'clean', 'since23']) + "  | " + fmt(out['all']), flush=True)
    return dict(name=name, **out)
R = []
D55 = U & (C > prev(hi(55))); X50 = C < sma(50)
HP = (C / hi(250)).where(U).rank(axis=1, pct=True)
ST = result_state('pr')
STf = ST.fillna(0.5)
S_rh = (RS + HP) / 2; S_rr = (RS + STf) / 2; S_all = (RS + HP + STf) / 3
for nm, sc in [('RS', RS), ('RS + 52wk-high proximity', S_rh), ('RS + result rank', S_rr), ('RS + 52wk-high + result', S_all)]:
    R.append(run(f'Trend D55/<50d score {nm}', entry=D55, score=sc, exit_sig=X50, min_hold=3, max_hold=250))
    R.append(run(f'Swing D20/<EMA10 score {nm}', entry=U & (C > prev(hi(20))), score=sc, exit_sig=C < ema(10), min_hold=2, max_hold=30))
# continuous ranking book: buy when composite rank is top 3% and price above 50-day; sell when composite rank < 70% or close < 50-day
CR = S_all.where(U).rank(axis=1, pct=True)
R.append(run('Continuous: composite top 3% in, <70% or <50d out', entry=U & (CR >= 0.97) & (C > sma(50)), score=CR, exit_sig=(CR < 0.7) | X50, min_hold=3, max_hold=500))
R.append(run('Continuous: composite top 3% in, <50d out', entry=U & (CR >= 0.97) & (C > sma(50)), score=CR, exit_sig=X50, min_hold=3, max_hold=500))
json.dump(R, open(rs2.S + '/data/swing_r6.json', 'w'), indent=1, default=float)
