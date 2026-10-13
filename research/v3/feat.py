# Earnings-event features (all known at the entry close) + forward excess returns.
import numpy as np, pandas as pd, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import rs2

def build(save=True):
    P = rs2.panel(); C = P['c']; dates = P['dates']; cv = C.values; mk = P['mkt'].values
    col = {k: i for i, k in enumerate(C.columns)}
    ev = rs2.results_events().copy()
    ev = ev[ev['isin'].isin(col)].copy()
    # ---- fundamentals history per isin (by fiscal quarter number) ----
    f = ev[['isin', 'qn', 'dilutedEPS', 'revenueYoyGrowth', 'patYoyGrowth', 'epsYoyGrowth', 'opmYoyBps', 'revenue', 'profitAfterTax', 'opm']].copy()
    key = f.set_index(['isin', 'qn'])
    def lag(colname, k):
        idx = list(zip(ev['isin'], ev.qn - k))
        return key[colname].reindex(idx).values
    ev['eps_l4'] = lag('dilutedEPS', 4)
    ev['pat_l1'] = lag('patYoyGrowth', 1); ev['rev_l1'] = lag('revenueYoyGrowth', 1)
    ev['pat_l2'] = lag('patYoyGrowth', 2); ev['rev_l2'] = lag('revenueYoyGrowth', 2)
    ev['opm_l1'] = lag('opmYoyBps', 1)
    ev['revenue_l4'] = lag('revenue', 4); ev['pat_abs_l4'] = lag('profitAfterTax', 4)
    # ---- price-based features at the entry index ----
    ei = np.array([int(dates.searchsorted(t.normalize(), side='right')) for t in ev.ts])
    ev['ei'] = ei
    ok = ei < len(dates)
    ev = ev[ok].copy(); ei = ev.ei.values
    ci = np.array([col[s] for s in ev['isin']])
    def px(off):
        j = ei + off; out = np.full(len(ei), np.nan)
        m = (j >= 0) & (j < len(dates)); out[m] = cv[j[m], ci[m]]; return out
    def mx(off):
        j = ei + off; out = np.full(len(ei), np.nan)
        m = (j >= 0) & (j < len(dates)); out[m] = mk[j[m]]; return out
    c0 = px(0); cpre = px(-2)
    ev['react'] = c0 / cpre - 1
    ev['react_x'] = ev.react - (mx(0) / mx(-2) - 1)
    ev['day2'] = px(1) / c0 - 1                                  # session after the reaction (known only at i+1)
    ev['run60'] = cpre / px(-62) - 1 - (mx(-2) / mx(-62) - 1)
    ev['run120'] = cpre / px(-122) - 1 - (mx(-2) / mx(-122) - 1)
    # 52w high / SMA200 at entry (using closes up to i)
    hi = np.full(len(ei), np.nan); sma200 = np.full(len(ei), np.nan); sma50 = np.full(len(ei), np.nan); lo52 = np.full(len(ei), np.nan)
    sma200_20 = np.full(len(ei), np.nan)
    for k in range(len(ei)):
        a = cv[max(0, ei[k] - 249): ei[k] + 1, ci[k]]
        a = a[np.isfinite(a)]
        if len(a) >= 120:
            hi[k] = a.max(); lo52[k] = a.min(); sma200[k] = a[-200:].mean(); sma50[k] = a[-50:].mean()
            b = cv[max(0, ei[k] - 269): ei[k] - 19, ci[k]]; b = b[np.isfinite(b)]
            if len(b) >= 120: sma200_20[k] = b[-200:].mean()
    ev['off_hi'] = c0 / hi - 1; ev['above_lo'] = c0 / lo52 - 1
    ev['above200'] = c0 / sma200 - 1; ev['sma50_200'] = sma50 / sma200 - 1; ev['sma200_up'] = sma200 / sma200_20 - 1
    ev['price0'] = c0; ev['cpre'] = cpre
    # PIT market cap approximation: current mcap scaled by price ratio
    last_c = C.ffill().iloc[-1]
    cur_mcap = ev.sort_values('qn').groupby('isin').marketCap.last()
    ev['mcap_pit'] = ev['isin'].map(cur_mcap).values * cpre / ev['isin'].map(last_c).values
    # earnings surprise scaled by price (SUE-p), seasonal random walk
    ev['sue_p'] = (ev.dilutedEPS - ev.eps_l4) / cpre * 4 * 100        # annualised change in EPS as % of price
    ev['pat_acc'] = ev.patYoyGrowth.clip(-100, 300) - ev.pat_l1.clip(-100, 300)
    ev['rev_acc'] = ev.revenueYoyGrowth.clip(-100, 300) - ev.rev_l1.clip(-100, 300)
    g = ev[['patYoyGrowth', 'pat_l1', 'pat_l2']]
    ev['pat_streak'] = (g > 15).sum(axis=1)
    ev['rev_streak'] = (ev[['revenueYoyGrowth', 'rev_l1', 'rev_l2']] > 10).sum(axis=1)
    # forward excess returns, entry at close of ei + lag (lag 1 = next session close, conservative)
    for lagk in (0, 1):
        e0 = px(lagk)
        for h in (20, 40, 60, 120):
            ev[f'x{h}_l{lagk}'] = px(lagk + h) / e0 - 1 - (mx(lagk + h) / mx(lagk) - 1)
            ev[f'r{h}_l{lagk}'] = px(lagk + h) / e0 - 1
    ev['yr'] = ev.ts.dt.year
    ev['period'] = np.where(ev.ts < '2025-01-01', 'train', 'test')
    if save: ev.to_pickle(f'{rs2.S}/data/feat_ev.pkl')
    return ev

def qtable(ev, feat, y='x60_l1', q=5, by='period'):
    d = ev[[feat, y, by]].replace([np.inf, -np.inf], np.nan).dropna()
    out = {}
    for p, g in d.groupby(by):
        b = pd.qcut(g[feat].rank(method='first'), q, labels=range(1, q + 1))
        t = g.groupby(b, observed=True)[y].agg(['count', 'median', lambda s: (s > 0).mean()])
        t.columns = ['n', 'med', 'hit']; out[p] = t
    return pd.concat(out, axis=1)
