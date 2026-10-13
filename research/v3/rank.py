# Continuous ranking portfolio: state = latest valid result (growth, reaction) + live price trend. Rebalance every k sessions.
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
import rs2, score, regime, numpy as np, pandas as pd

def trend_mats():
    P = rs2.panel(); c = P['c'].astype('float64')
    cache = rs2.S + '/data/trend_mats.pkl'
    if os.path.exists(cache): return pd.read_pickle(cache)
    m = P['mkt']
    sma200 = c.rolling(200, min_periods=150).mean(); sma50 = c.rolling(50, min_periods=40).mean()
    hi = c.rolling(250, min_periods=120).max(); lo = c.rolling(250, min_periods=120).min()
    ret120 = c / c.shift(120) - 1; mret120 = m / m.shift(120) - 1
    ret250 = c / c.shift(250) - 1
    T = dict(above200=c / sma200 - 1, off_hi=c / hi - 1, above_lo=c / lo - 1, sma200_up=sma200 / sma200.shift(20) - 1,
             rs120=ret120.sub(mret120, axis=0), sma50_200=sma50 / sma200 - 1, rs250=ret250)
    pd.to_pickle(T, cache)
    return T

def state_panel(ev, max_age=130):
    """for each date: latest valid result per isin (age <= max_age sessions) with its season-relative growth & reaction ranks."""
    ev = ev.copy(); ev['sue_p'] = ev.sue_p.clip(-20, 20)
    for c_ in ['revenueYoyGrowth', 'patYoyGrowth', 'sue_p', 'opmYoyBps', 'react_x', 'pat_streak', 'rev_streak']:
        ev['pr_' + c_] = ev.groupby('qn')[c_].rank(pct=True)
    ev['g_growth'] = ev[['pr_revenueYoyGrowth', 'pr_patYoyGrowth', 'pr_sue_p', 'pr_opmYoyBps']].mean(axis=1)
    ev['g_react'] = ev['pr_react_x']
    return ev

def run(ev, top_n=20, sell_rank=60, every=10, w=dict(growth=2, react=1, trend=1), start='2022-07-01', end=None, cost=0.003,
        exposure=None, max_age=130, min_mcap=500, req=None, trend_cols=('above200', 'off_hi', 'sma200_up', 'rs120'),
        lag=1, min_turn=None, max_day=None):
    P = rs2.panel(); C = P['c']; dates = P['dates']; cv = C.values; col = {k: i for i, k in enumerate(C.columns)}
    T = trend_mats(); ev = state_panel(ev)
    ev = ev[ev.mcap_pit >= min_mcap] if min_mcap else ev
    ev = ev.sort_values('ei')
    s_i = dates.searchsorted(pd.Timestamp(start)); e_i = dates.searchsorted(pd.Timestamp(end), side='right') - 1 if end else len(dates) - 1
    ex = exposure.reindex(dates).ffill().fillna(1).values if exposure is not None else np.ones(len(dates))
    hold = {}; daily = []; trades = []; last_rank = None; pend_buy = []; pend_sell = []
    V = P['v']; turn = (C * V / 1e7).rolling(20, min_periods=10).median() if min_turn else None
    dret = C.pct_change(fill_method=None)
    evv = ev[['isin', 'ei', 'g_growth', 'g_react', 'patYoyGrowth', 'revenueYoyGrowth', 'react', 'companySector']].values
    for i in range(s_i, e_i + 1):
        px = cv[i]
        # daily P&L
        rets = []
        for k, p in hold.items():
            c_ = px[col[k]]
            if np.isfinite(c_): rets.append(c_ / p['last'] - 1); p['last'] = c_
            else: rets.append(0.0)
        r = np.mean(rets) * (len(hold) / top_n) if hold else 0.0
        n_tr = 0
        # execute yesterday's decisions at today's close (lag=1)
        for k in pend_sell:
            if k in hold:
                p = hold.pop(k); n_tr += 1
                trades.append(dict(isin=k, ed=dates[p['ei']], xd=dates[i], ret=px[col[k]] / p['entry'] - 1 - 2 * cost if np.isfinite(px[col[k]]) else np.nan, days=i - p['ei']))
        for k in pend_buy:
            if k not in hold and len(hold) < top_n:
                c_ = px[col[k]]
                if np.isfinite(c_): hold[k] = dict(ei=i, entry=c_, last=c_); n_tr += 1
        pend_buy, pend_sell = [], []
        if (i - s_i) % every == 0:
            # state: latest result per isin known by close of i (entry index <= i)
            st = ev[(ev.ei <= i) & (ev.ei > i - max_age)].drop_duplicates('isin', keep='last').set_index('isin')
            st = st[st.index.isin(col)]
            if len(st) > 50:
                tr = pd.DataFrame({k: T[k].iloc[i] for k in trend_cols}).reindex(st.index)
                trank = tr.rank(pct=True).mean(axis=1)
                sc = (w['growth'] * st.g_growth.fillna(0.5) + w['react'] * st.g_react.fillna(0.5) + w['trend'] * trank.fillna(0.5)) / sum(w.values())
                ok = pd.Series(np.isfinite(px[[col[k] for k in st.index]]) & (px[[col[k] for k in st.index]] >= 20), index=st.index)
                if req is not None: ok &= req(st, tr)
                if min_turn is not None and i < len(dates):
                    tv = turn.iloc[i].reindex(st.index)
                    big = st.mcap_pit >= 1000
                    ok &= np.where(tv.notna(), tv >= min_turn, big)
                if max_day is not None:
                    ok &= (dret.iloc[i].reindex(st.index).fillna(0) < max_day)
                sc = sc[ok].sort_values(ascending=False)
                rk = pd.Series(np.arange(1, len(sc) + 1), index=sc.index)
                # sells: dropped below sell_rank (or no longer has a valid state)
                sells = [k for k in hold if k not in rk.index or rk[k] > sell_rank]
                keep = [k for k in hold if k not in sells]
                cap = int(round(top_n * ex[i]))
                if len(keep) > cap:
                    keep_sorted = sorted(keep, key=lambda z: rk.get(z, 1e9)); sells += keep_sorted[cap:]; keep = keep_sorted[:cap]
                buys = [k for k in rk.index if k not in hold][:max(0, cap - len(keep))]
                if lag == 0:
                    for k in sells:
                        p = hold.pop(k); n_tr += 1
                        trades.append(dict(isin=k, ed=dates[p['ei']], xd=dates[i], ret=px[col[k]] / p['entry'] - 1 - 2 * cost if np.isfinite(px[col[k]]) else np.nan, days=i - p['ei']))
                    for k in buys:
                        c_ = px[col[k]]; hold[k] = dict(ei=i, entry=c_, last=c_); n_tr += 1
                else:
                    pend_sell, pend_buy = sells, buys
                last_rank = rk
        r -= n_tr * cost / top_n
        daily.append((dates[i], r, len(hold)))
    D = pd.DataFrame(daily, columns=['d', 'r', 'n']).set_index('d'); D['equity'] = (1 + D.r).cumprod()
    return dict(eq=D, trades=pd.DataFrame(trades), hold=hold, rank=last_rank)
