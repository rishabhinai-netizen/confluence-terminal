# Round 7: swing robustness grid + combined books over the full period.
import json
from swing import *
U = univ(); RS = rs_rank(126); prev = lambda df, k=1: df.shift(k)
PER = {'design': ('2018-07-01', '2022-12-31'), 'valid': ('2023-01-01', '2024-12-31'), 'clean': ('2025-01-01', None), 'all': ('2018-07-01', None)}
EQ = {}
def run(name, keep=False, **kw):
    out = {}
    for per, (a, b) in PER.items():
        D, T = simulate(start=a, end=b, **kw); out[per] = stats(D, T, name)
        if keep and per == 'all': EQ[name] = (D, T)
    print(" ".join(f"{out[p]['cagr']*100:5.1f}/{out[p]['dd']*100:4.0f}" for p in ['design', 'valid', 'clean']) + "  | " + fmt(out['all']), flush=True)
    return dict(name=name, **out)
R = []
for n in (10, 20, 30):
    for ex in (('EMA10', C < ema(10)), ('EMA20', C < ema(20)), ('5-day low', C < prev(lo(5)))):
        R.append(run(f'Swing D{n} exit {ex[0]}', keep=(n == 20 and ex[0] == 'EMA10'), entry=U & (C > prev(hi(n))), score=RS, exit_sig=ex[1], min_hold=2, max_hold=30))
R.append(run('Trend D55 exit <50d', keep=True, entry=U & (C > prev(hi(55))), score=RS, exit_sig=C < sma(50), min_hold=3, max_hold=250))
pd.to_pickle(EQ, rs2.S + '/data/books2_eq.pkl')
r = pd.DataFrame({k: v[0].r for k, v in EQ.items()}).fillna(0)
print(r.corr().round(2).to_string())
for w in [(1, 0), (0, 1), (.5, .5), (.6, .4), (.7, .3)]:
    x = r.iloc[:, 0] * w[0] + r.iloc[:, 1] * w[1]; eq = (1 + x).cumprod(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    y = eq.resample('YE').last(); pv = np.r_[1.0, y.values[:-1]]
    print(w, list(r.columns), f"{(eq.iloc[-1] ** (1 / yrs) - 1)*100:.1f}% dd {(eq / eq.cummax() - 1).min()*100:.1f}", {k.year: round((a / b - 1) * 100) for k, a, b in zip(y.index, y.values, pv)})
json.dump(R, open(rs2.S + '/data/swing_r7.json', 'w'), indent=1, default=float)
