# Research core: price panel + event study.
# Entry rule (no look-ahead): an event known at time T is entered at the CLOSE of the first trading day
# strictly after the day the information became public (after-hours events -> next session; that is what a
# person reading the page that evening could actually do). Excess = stock return - equal-weight universe return
# over the same window. Daily universe returns are clipped at +-40% to dampen bad prints.
import json, numpy as np, pandas as pd, os
S = os.environ.get('CT_SCRATCH', '/tmp/ct-scratch')
_P = {}

def panel():
    if _P: return _P
    cache = f'{S}/data/px/panel.pkl'
    if os.path.exists(cache):
        _P.update(pd.read_pickle(cache)); return _P
    C, O, V = {}, {}, {}
    for line in open(f'{S}/data/px/prices.jsonl'):
        r = json.loads(line)
        idx = pd.to_datetime(r['d'])
        C[r['isin']] = pd.Series(r['c'], index=idx, dtype='float64')
        O[r['isin']] = pd.Series(r['o'], index=idx, dtype='float64')
        V[r['isin']] = pd.Series(r['v'], index=idx, dtype='float64')
    c = pd.DataFrame(C).sort_index(); o = pd.DataFrame(O).reindex(c.index); v = pd.DataFrame(V).reindex(c.index)
    turn = (c * v / 1e7)  # Rs crore traded
    ret = c.pct_change(fill_method=None).clip(-0.4, 0.4)
    # universe = stocks with >= Rs 2 cr median 20d turnover (tradeable), equal weight
    liq = turn.rolling(20, min_periods=10).median() >= 2
    mkt = ret.where(liq.shift(1, fill_value=False)).mean(axis=1).fillna(0)
    mkt_idx = (1 + mkt).cumprod()
    _P.update(dict(c=c, o=o, v=v, turn=turn, mkt=mkt_idx, dates=c.index, liq=liq))
    pd.to_pickle(dict(_P), cache)
    return _P

def entry_index(ts):
    """index of first trading day strictly after the calendar day of ts (ts may be datetime or date str)."""
    P = panel(); d = pd.Timestamp(ts).normalize()
    return int(P['dates'].searchsorted(d, side='right'))

def fwd(isin, ts, horizons=(5, 20, 40, 60), entry='after'):
    """returns dict h -> (raw, excess); None if not enough data. entry='after' -> close of first session after ts's day;
       entry='on' -> close of ts's day (only for information available before that day's close)."""
    P = panel(); c = P['c']
    if isin not in c.columns: return None
    i = entry_index(ts) if entry == 'after' else int(P['dates'].searchsorted(pd.Timestamp(ts).normalize(), side='left'))
    if i >= len(P['dates']): return None
    col = c[isin].values; m = P['mkt'].values
    p0 = col[i]
    if not np.isfinite(p0) or p0 <= 0: return None
    out = {}
    for h in horizons:
        j = i + h
        if j >= len(col): out[h] = None; continue
        p1 = col[j]
        if not np.isfinite(p1):
            # walk back to last valid print within window (suspension) — treat as held
            seg = col[i:j+1]; ok = np.where(np.isfinite(seg))[0]
            if not len(ok): out[h] = None; continue
            p1 = seg[ok[-1]]
        raw = p1 / p0 - 1; mk = m[j] / m[i] - 1
        out[h] = (raw, raw - mk)
    return out

def summarize(df, group_col, h, min_n=25):
    """df has columns group_col and f'x{h}' (excess) and f'r{h}' (raw)."""
    rows = []
    for g, sub in df.groupby(group_col, dropna=False):
        x = sub[f'x{h}'].dropna()
        if len(x) < min_n: continue
        rows.append(dict(group=g, n=len(x), hit=round((x > 0).mean() * 100, 1), med=round(x.median() * 100, 2),
                         mean=round(x.clip(-0.6, 1.5).mean() * 100, 2), p25=round(x.quantile(.25) * 100, 2), p75=round(x.quantile(.75) * 100, 2)))
    return pd.DataFrame(rows).sort_values('med', ascending=False) if rows else pd.DataFrame()

def attach(df, isin_col='isin', ts_col='ts', horizons=(5, 20, 40, 60), entry='after'):
    res = {f'x{h}': [] for h in horizons}; res.update({f'r{h}': [] for h in horizons})
    for isin, ts in zip(df[isin_col], df[ts_col]):
        f = fwd(isin, ts, horizons, entry) if isinstance(isin, str) and pd.notna(ts) else None
        for h in horizons:
            v = f.get(h) if f else None
            res[f'r{h}'].append(v[0] if v else np.nan); res[f'x{h}'].append(v[1] if v else np.nan)
    for k, v in res.items(): df[k] = v
    return df
