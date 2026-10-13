# Swing / any-day research kit: indicators on the 2018-2026 panel and a slot portfolio simulator with stops.
# Prices: adjusted close + low from 2018, full OHLCV from Jan 2025. Signals use the close of day d.
import sys, os, json, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import rs2, strat
P = rs2.panel()
C = P['c'].astype('float64'); L = P['l'].astype('float64'); H = P['h'].astype('float64'); O = P['o'].astype('float64'); V = P['v'].astype('float64')
DATES = P['dates']; ISINS = C.columns
_cache = {}

def cached(name, fn):
    if name not in _cache: _cache[name] = fn()
    return _cache[name]

def sma(n): return cached(f'sma{n}', lambda: C.rolling(n, min_periods=int(n * 0.9)).mean())
def ema(n): return cached(f'ema{n}', lambda: C.ewm(span=n, min_periods=n, adjust=False).mean())
def hi(n): return cached(f'hi{n}', lambda: C.rolling(n, min_periods=int(n * 0.9)).max())          # highest CLOSE of last n incl today
def lo(n): return cached(f'lo{n}', lambda: C.rolling(n, min_periods=int(n * 0.9)).min())
def ret(n): return cached(f'ret{n}', lambda: C / C.shift(n) - 1)
def rsi(n):
    def f():
        d = C.diff(); up = d.clip(lower=0); dn = (-d).clip(lower=0)
        au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean(); ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        return 100 - 100 / (1 + au / ad.replace(0, np.nan))
    return cached(f'rsi{n}', f)
def vol(n): return cached(f'vol{n}', lambda: C.pct_change(fill_method=None).rolling(n, min_periods=int(n * 0.8)).std())
def mret(n):
    m = P['mkt']; return m / m.shift(n) - 1
def rs_rank(n):   # cross-sectional percentile of n-day return (within the tradeable universe)
    return cached(f'rsr{n}', lambda: ret(n).where(univ()).rank(axis=1, pct=True))

def mcap_now():
    def f():
        ev = rs2.results_events().sort_values('ts')
        m = ev.groupby('isin').marketCap.last()
        return m.reindex(ISINS)
    return cached('mcap_now', f)
def univ(min_mcap=1000, min_turn=5):
    def f():
        last = C.ffill().iloc[-1]
        mc = C.mul(mcap_now() / last, axis=1)                         # point-in-time mcap approximation
        turn = (C * V / 1e7).rolling(20, min_periods=10).median()      # Rs cr, 2025+ only
        ok = (C >= 20) & (C.notna().cumsum() >= 200) & (mc >= min_mcap)
        ok &= turn.isna() | (turn >= min_turn)
        return ok
    return cached(f'univ{min_mcap}_{min_turn}', f)

GAUGE = strat.exposure('vote3').reindex(DATES).ffill().fillna(1)     # known the evening before (already shifted)

def simulate(entry, score, slots=10, lag=1, stop=None, stop_px=None, target=None, exit_sig=None, max_hold=20, min_hold=0,
             cost=0.003, start='2018-07-01', end=None, regime='scale', trail=None, size=None, size_df=None, exit_lag=0, dstop=None, slip=0.005):
    """entry: bool DataFrame (signal at close d); score: DataFrame to rank same-day signals (higher first).
    lag=1 buys at the next close (conservative), lag=0 at the signal close.
    stop: fraction below entry (e.g. 0.07); stop_px: DataFrame of stop prices fixed at signal day (overrides stop).
    target: fraction above entry (exit at close once reached; at target price when the high is known).
    exit_sig: bool DataFrame, exit at that close. trail: fraction below highest close since entry.
    regime: 'scale' (new size = gauge, none at 0), 'block' (no buys when gauge < 0.5), None."""
    cv, lv, hv, ov = C.values, L.values, H.values, O.values
    ev = entry.reindex(index=DATES, columns=ISINS).fillna(False).values
    sv = score.reindex(index=DATES, columns=ISINS).values
    xv = exit_sig.reindex(index=DATES, columns=ISINS).fillna(False).values if exit_sig is not None else None
    spv = stop_px.reindex(index=DATES, columns=ISINS).values if stop_px is not None else None
    gz = GAUGE.values
    zv = size_df.reindex(index=DATES, columns=ISINS).values if size_df is not None else None
    dsv = dstop.reindex(index=DATES, columns=ISINS).values if dstop is not None else None
    s_i = DATES.searchsorted(pd.Timestamp(start)); e_i = DATES.searchsorted(pd.Timestamp(end), side='right') - 1 if end else len(DATES) - 1
    pos = {}; pend = []; daily = []; trades = []
    for i in range(s_i, e_i + 1):
        r = 0.0; ntr = 0
        # 1) manage open positions at today's prices
        for k in list(pos):
            p = pos[k]; c0 = cv[i, k]
            if not np.isfinite(c0): continue
            lw = lv[i, k] if np.isfinite(lv[i, k]) else c0; hh = hv[i, k] if np.isfinite(hv[i, k]) else c0
            px, why = None, None
            if dsv is not None and i - p['i'] >= min_hold and np.isfinite(dsv[i - 1, k]) and lw <= dsv[i - 1, k]:
                o0 = ov[i, k]; lvl = dsv[i - 1, k]
                px = min(lvl, o0) if np.isfinite(o0) else lvl * (1 - slip); why = 'trail stop'
            elif p['stop'] is not None and lw <= p['stop']:
                o0 = ov[i, k]
                px = min(p['stop'], o0) if np.isfinite(o0) else p['stop'] * 0.99; why = 'stop'   # gap fills at the open; before 2025 (no open) assume 1% slippage
            elif p['tgt'] is not None and hh >= p['tgt']:
                px = p['tgt'] if np.isfinite(hv[i, k]) else c0; why = 'target'
            elif p.get('xpend'):
                px = c0; why = p['xpend']
            elif xv is not None and xv[i, k] and i - p['i'] >= min_hold:
                if exit_lag: p['xpend'] = 'signal'
                else: px = c0; why = 'signal'
            elif trail is not None and c0 < p['peak'] * (1 - trail):
                if exit_lag: p['xpend'] = 'trail'
                else: px = c0; why = 'trail'
            elif i - p['i'] >= max_hold:
                if exit_lag: p['xpend'] = 'time'
                else: px = c0; why = 'time'
            if px is not None:
                r += (px / p['last'] - 1) * p['w'] / slots
                trades.append((ISINS[k], DATES[p['i']], DATES[i], px / p['entry'] - 1 - 2 * cost, why, i - p['i'], p['w']))
                del pos[k]; ntr += p['w']; continue
            r += (c0 / p['last'] - 1) * p['w'] / slots; p['last'] = c0; p['peak'] = max(p['peak'], c0)
        # 2) execute pending buys at today's close (lag=1) or decide-and-buy today (lag=0)
        todays = []
        js = np.where(ev[i])[0]
        if len(js):
            sc = sv[i, js]; order = js[np.argsort(-np.nan_to_num(sc, nan=-1e9))]
            todays = [(k, i) for k in order]
        if lag == 1: buy_list, pend = pend, todays
        else: buy_list = todays
        g = gz[i]
        w = (size if size is not None else 1.0) * (g if regime == 'scale' else 1.0)
        allow = not ((regime == 'scale' and g <= 0) or (regime == 'block' and g < 0.5))
        for k, si in buy_list:
            if not allow or len(pos) >= slots: break
            if k in pos: continue
            c0 = cv[i, k]
            if not np.isfinite(c0) or c0 <= 0: continue
            if spv is not None and np.isfinite(spv[si, k]): st = spv[si, k] if spv[si, k] < c0 else None
            elif stop is not None: st = c0 * (1 - stop)
            else: st = None
            wk = w * (float(np.clip(zv[si, k], 0.3, 2.0)) if zv is not None and np.isfinite(zv[si, k]) else 1.0)
            pos[k] = dict(i=i, entry=c0, last=c0, peak=c0, stop=st, tgt=c0 * (1 + target) if target else None, w=wk); ntr += wk
        r -= ntr * cost / slots
        daily.append((DATES[i], r, len(pos), sum(p['w'] for p in pos.values()) / slots))
    D = pd.DataFrame(daily, columns=['d', 'r', 'n', 'expo']).set_index('d'); D['equity'] = (1 + D.r).cumprod()
    T = pd.DataFrame(trades, columns=['isin', 'ed', 'xd', 'ret', 'why', 'days', 'w'])
    return D, T

def stats(D, T, name=''):
    eq = D.equity; yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    y = eq.resample('YE').last(); prev = np.r_[1.0, y.values[:-1]]
    w = T[T.ret > 0].ret; l = T[T.ret <= 0].ret
    return dict(name=name, cagr=float(eq.iloc[-1] ** (1 / yrs) - 1), dd=float((eq / eq.cummax() - 1).min()), trades=int(len(T)),
                win=float((T.ret > 0).mean()) if len(T) else None, avg=float(T.ret.mean()) if len(T) else None,
                avg_win=float(w.mean()) if len(w) else None, avg_loss=float(l.mean()) if len(l) else None,
                pf=float(w.sum() / -l.sum()) if len(l) and l.sum() < 0 else None, days=float(T.days.mean()) if len(T) else None,
                expo=float(D.expo.mean()), yearly={str(k.year): float(v) for k, v in zip(y.index, y.values / prev - 1)},
                mar=float((eq.iloc[-1] ** (1 / yrs) - 1) / -min((eq / eq.cummax() - 1).min(), -1e-9)))

def fmt(s):
    yy = ' '.join(f"{k[2:]}:{v*100:+5.0f}" for k, v in s['yearly'].items())
    return f"{s['cagr']*100:6.1f}% dd{s['dd']*100:6.1f} MAR{s['mar']:4.2f} n{s['trades']:5d} win{(s['win'] or 0)*100:3.0f} avg{(s['avg'] or 0)*100:5.2f} pf{(s['pf'] or 0):4.2f} d{(s['days'] or 0):4.1f} ex{s['expo']*100:3.0f} | {yy} | {s['name']}"

def result_state(col='pr', max_age=130, ev=None):
    """Latest result's value per stock on each day (point in time: known from its entry index ei), dropped after max_age sessions."""
    def f():
        e = ev if ev is not None else pd.read_pickle(rs2.S + '/data/ev_pit.pkl')
        e = e[e[col].notna() & e['isin'].isin(set(ISINS))].sort_values('ei')
        M = pd.DataFrame(np.nan, index=DATES, columns=ISINS)
        A = pd.DataFrame(np.nan, index=DATES, columns=ISINS)
        for isin, ei, v in zip(e['isin'], e['ei'], e[col]):
            M.iat[int(ei), ISINS.get_loc(isin)] = v; A.iat[int(ei), ISINS.get_loc(isin)] = int(ei)
        M = M.ffill(); A = A.ffill()
        age = pd.DataFrame(np.repeat(np.arange(len(DATES))[:, None], len(ISINS), axis=1), index=DATES, columns=ISINS) - A
        return M.where(age <= max_age)
    return cached(f'state_{col}_{max_age}', f)

def clenow(n=90):
    """Clenow 'Stocks on the Move' momentum: annualised exponential regression slope x R^2 over n sessions."""
    def f():
        y = np.log(C); x = np.arange(n, dtype=float); xm = x.mean(); sxx = ((x - xm) ** 2).sum()
        out = pd.DataFrame(np.nan, index=DATES, columns=ISINS)
        Y = y.values
        for i in range(n - 1, len(DATES)):
            w = Y[i - n + 1:i + 1]
            ok = np.isfinite(w).all(axis=0)
            if not ok.any(): continue
            ww = w[:, ok]; ym = ww.mean(axis=0)
            b = ((x - xm)[:, None] * (ww - ym)).sum(axis=0) / sxx
            fit = ym + b * (x - xm)[:, None]
            r2 = 1 - ((ww - fit) ** 2).sum(axis=0) / np.maximum(((ww - ym) ** 2).sum(axis=0), 1e-12)
            row = np.full(len(ISINS), np.nan); row[ok] = ((np.exp(b) ** 250) - 1) * r2
            out.iloc[i] = row
        return out
    return cached(f'clenow{n}', f)

def outcomes(entry, exit_sig, min_hold=3, max_hold=250, lag=1, cost=0.003, fresh=20):
    """Every signal as an independent trade (no slot limit): entry at close d+lag, exit at the first close >= entry+min_hold where exit_sig.
    fresh: ignore a signal if the same stock signalled in the previous `fresh` sessions. Returns a DataFrame (one row per trade)."""
    ev = entry.reindex(index=DATES, columns=ISINS).fillna(False).values
    xv = exit_sig.reindex(index=DATES, columns=ISINS).fillna(False).values
    cv = C.values; n = len(DATES); rows = []
    for k in range(len(ISINS)):
        sig = np.where(ev[:, k])[0]
        if not len(sig): continue
        xs = np.where(xv[:, k])[0]
        last = -10 ** 9
        for d in sig:
            if d - last <= fresh: last = d; continue
            last = d
            e = d + lag
            if e >= n or not np.isfinite(cv[e, k]): continue
            j0 = e + min_hold; p = np.searchsorted(xs, j0)
            x = xs[p] if p < len(xs) and xs[p] <= e + max_hold else min(e + max_hold, n - 1)
            open_ = not (p < len(xs) and xs[p] <= e + max_hold) and e + max_hold > n - 1
            cx = cv[x, k]
            if not np.isfinite(cx):
                ff = cv[e:x + 1, k]; ff = ff[np.isfinite(ff)]; cx = ff[-1]
            rows.append((ISINS[k], d, e, x, cx / cv[e, k] - 1 - 2 * cost, x - e, open_))
    return pd.DataFrame(rows, columns=['isin', 'd', 'e', 'x', 'ret', 'days', 'open'])

def osum(T, name=''):
    T = T[~T.open]; w = T.ret[T.ret > 0]; l = T.ret[T.ret <= 0]
    return dict(name=name, n=len(T), avg=T.ret.mean(), med=T.ret.median(), win=(T.ret > 0).mean(), pf=w.sum() / -l.sum() if len(l) else np.nan,
                days=T.days.mean(), per_day=T.ret.sum() / T.days.sum())
