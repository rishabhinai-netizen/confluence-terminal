# Which data adds edge to a breakout? Every fresh 55-day-high breakout as an independent trade (exit: close below 50-day avg).
import json
from swing import *
T = pd.read_pickle(rs2.S + '/data/out_d55.pkl'); T = T[~T.open].copy()
kk = T['isin'].map({k: i for i, k in enumerate(ISINS)}).values; dd = T.d.values
at = lambda M: M.values[dd, kk] if isinstance(M, pd.DataFrame) else M
T['yr'] = DATES[dd].year
T['rs'] = at(rs_rank(126)); T['gauge'] = GAUGE.values[np.minimum(dd + 1, len(DATES) - 1)]
T['ext50'] = at(C / sma(50) - 1); T['ext200'] = at(C / sma(200) - 1)
T['vol'] = at(vol(20)); T['run20'] = at(ret(20)); T['run250'] = at(ret(250))
T['mc'] = at(C.mul(mcap_now() / C.ffill().iloc[-1], axis=1))
T['tight'] = at((hi(20) / lo(20) - 1).shift(1))
T['vr'] = at(V / V.rolling(50, min_periods=30).mean())
ST = result_state('pr'); T['res'] = at(ST)
AGE = None
def tab(col, bins, name, sub=None):
    X = T if sub is None else T[sub]
    g = X.groupby(pd.cut(X[col], bins), observed=True).ret
    out = pd.DataFrame({'n': g.size(), 'avg%': g.mean() * 100, 'win%': g.apply(lambda s: (s > 0).mean() * 100), 'pf': g.apply(lambda s: s[s > 0].sum() / -s[s <= 0].sum())})
    print(f'\n== {name}'); print(out.round(2).to_string()); return out
R = {}
R['rs'] = tab('rs', [0, .5, .7, .8, .9, .95, 1.0], 'RS 126 percentile (all years)')
R['rs_25'] = tab('rs', [0, .5, .7, .8, .9, .95, 1.0], 'RS 126 percentile (2025+)', T.yr >= 2025)
R['gauge'] = tab('gauge', [-.1, .1, .4, .7, 1.1], 'Market gauge next day')
R['ext50'] = tab('ext50', [-1, .05, .1, .15, .2, .3, 5], 'Distance above 50-day avg at breakout')
R['run250'] = tab('run250', [-1, 0, .3, .6, 1, 2, 50], '1-year return before breakout')
R['tight'] = tab('tight', [0, .08, .12, .16, .2, .3, 5], 'Prior 20-day range (base tightness)')
R['vol'] = tab('vol', [0, .015, .02, .025, .03, .04, 1], 'Daily volatility (20d)')
R['mc'] = tab('mc', [0, 2000, 5000, 15000, 50000, 1e9], 'Market cap (Rs cr)')
R['res'] = tab('res', [-.01, .3, .5, .7, .9, 1.0], 'Latest result rank (2023+)', T.yr >= 2023)
R['res_na'] = print('\nresults state missing (2023+):', T[(T.yr >= 2023) & T.res.isna()].ret.agg(['count', 'mean']).to_dict())
R['vr'] = tab('vr', [0, 1, 1.5, 2, 3, 100], 'Volume vs 50-day avg on breakout day (2025+)', T.yr >= 2025)
T.to_pickle(rs2.S + '/data/out_d55_feat.pkl')
