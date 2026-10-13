# Legend league for any-day setups, executable exits (signal at close -> act next close; stops intraday), entries next close.
import json
from swing_tests import SET
from swing import *
U = univ(); RS = rs_rank(126); prev = lambda df, k=1: df.shift(k)
SET = dict(SET)
SET['Turtle: 55-day breakout, exit below 50-day average (Trend book)'] = dict(entry=U & (C > prev(hi(55))), score=RS, dstop=sma(50), min_hold=3, max_hold=250)
SET['10-day breakout, exit below 10-day EMA (Swing book)'] = dict(entry=U & (C > prev(hi(10))), score=RS, exit_sig=C < ema(10), min_hold=2, max_hold=30)
out = []
for name, kw in SET.items():
    kw = dict(kw); 
    if 'exit_sig' in kw: kw['exit_lag'] = 1
    res = {}
    for per, (a, b) in {'all': ('2018-07-01', None), 'design': ('2018-07-01', '2022-12-31'), 'since23': ('2023-01-01', None)}.items():
        D, T = simulate(start=a, end=b, **kw); res[per] = stats(D, T, name)
    out.append(dict(name=name, **res)); print(fmt(res['all']), '| since23', round(res['since23']['cagr'] * 100, 1), flush=True)
json.dump(out, open(rs2.S + '/data/league4.json', 'w'), indent=1, default=float)
