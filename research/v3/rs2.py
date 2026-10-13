# Research base v2: long price panel (2018 ->), results events FY22 ->, portfolio backtester.
import json, glob, os, numpy as np, pandas as pd
S = __import__('os').environ.get('CT_WORK', './work')
_P = {}

def panel():
    if _P: return _P
    cache = f'{S}/data/px/panel2.pkl'
    if os.path.exists(cache):
        _P.update(pd.read_pickle(cache)); return _P
    C, L = {}, {}
    for line in open(f'{S}/data/px/hist.jsonl'):
        r = json.loads(line); idx = pd.to_datetime(r['d'])
        C[r['isin']] = pd.Series(r['c'], index=idx, dtype='float64'); L[r['isin']] = pd.Series(r['l'], index=idx, dtype='float64')
    C2, L2, O2, H2, V2 = {}, {}, {}, {}, {}
    for line in open(f'{S}/data/px/prices.jsonl'):
        r = json.loads(line); idx = pd.to_datetime(r['d'])
        C2[r['isin']] = pd.Series(r['c'], index=idx, dtype='float64'); L2[r['isin']] = pd.Series(r['l'], index=idx, dtype='float64')
        O2[r['isin']] = pd.Series(r['o'], index=idx, dtype='float64'); H2[r['isin']] = pd.Series(r['h'], index=idx, dtype='float64')
        V2[r['isin']] = pd.Series(r['v'], index=idx, dtype='float64')
    c1, c2 = pd.DataFrame(C), pd.DataFrame(C2)
    l1, l2 = pd.DataFrame(L), pd.DataFrame(L2)
    c = pd.concat([c1, c2]).sort_index(); c = c[~c.index.duplicated(keep='last')]
    l = pd.concat([l1, l2]).sort_index(); l = l[~l.index.duplicated(keep='last')].reindex(columns=c.columns)
    # keep only real trading days (>= 300 stocks priced)
    good = c.notna().sum(axis=1) >= 300
    c, l = c[good], l[good]
    o = pd.DataFrame(O2).reindex(index=c.index, columns=c.columns); h = pd.DataFrame(H2).reindex(index=c.index, columns=c.columns)
    v = pd.DataFrame(V2).reindex(index=c.index, columns=c.columns)
    c = c.astype('float32'); l = l.astype('float32'); o = o.astype('float32'); h = h.astype('float32'); v = v.astype('float32')
    ret = c.pct_change(fill_method=None).clip(-0.35, 0.35)
    # universe: price >= 20 and >= 120 sessions of history (no volume before 2025; survivorship noted)
    hist_n = c.notna().cumsum()
    univ = (c >= 20) & (hist_n >= 120)
    mkt = ret.where(univ.shift(1, fill_value=False)).mean(axis=1).fillna(0)
    mkt_idx = (1 + mkt).cumprod()
    _P.update(dict(c=c, l=l, o=o, h=h, v=v, ret=ret.astype('float32'), univ=univ, mkt=mkt_idx, mret=mkt, dates=c.index))
    pd.to_pickle(dict(_P), cache)
    return _P

def results_events():
    cache = f'{S}/data/res_ev2.pkl'
    if os.path.exists(cache) and os.path.getmtime(cache) > max(os.path.getmtime(f) for f in glob.glob(f'{S}/data/es/results_Q*.jsonl')):
        return pd.read_pickle(cache)
    KEEP = ['id', 'isin', 'symbol', 'companyName', 'companySector', 'quarter', 'fy', 'type', 'resultAnnouncementEpoch', 'revenue', 'ebitda',
            'profitAfterTax', 'opm', 'dilutedEPS', 'revenueYoyGrowth', 'ebitdaYoyGrowth', 'patYoyGrowth', 'opmYoyBps', 'epsYoyGrowth',
            'revenueSeqGrowth', 'patSeqGrowth', 'opmSeqBps', 'resultVerdict', 'balanceSheetHealth', 'peadLabel', 'marketCap', 'hohGrowth',
            'lflPatYoyGrowth', 'lflRevenueYoyGrowth', 'growthBasis', 'status', 'dataVerified']
    rows = []
    for f in glob.glob(f'{S}/data/es/results_Q*.jsonl'):
        for l in open(f):
            r = json.loads(l); rows.append({k: r.get(k) for k in KEEP})
    df = pd.DataFrame(rows).drop_duplicates('id')
    df = df[(df.status == 'COMPLETED') & df.resultAnnouncementEpoch.notna() & df['isin'].notna()].copy()
    df['ts'] = pd.to_datetime(df.resultAnnouncementEpoch, unit='ms', utc=True).dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
    qend = {1: (6, 30), 2: (9, 30), 3: (12, 31), 4: (3, 31)}
    df['qend'] = [pd.Timestamp(fy - (0 if q == 4 else 1), qend[q][0], qend[q][1]) for q, fy in zip(df.quarter, df.fy)]
    df['lag_days'] = (df.ts.dt.normalize() - df.qend).dt.days
    df = df[(df.lag_days >= 0) & (df.lag_days <= 120)]           # re-filings excluded
    df['qn'] = df.fy * 4 + df.quarter                              # sortable quarter number
    df = df.sort_values(['isin', 'qn', 'ts']).drop_duplicates(['isin', 'qn'], keep='first')
    df.to_pickle(cache)
    return df

def entry_index(ts):
    P = panel(); return int(P['dates'].searchsorted(pd.Timestamp(ts).normalize(), side='right'))

# ---------------- portfolio backtester ----------------
def backtest(signals, max_pos=10, hold=60, stop=None, trail=None, cost=0.003, start=None, end=None, exposure=None,
             sector_cap=None, entry_lag=1, rank_col='score', min_price=20):
    """signals: DataFrame [d (signal date, Timestamp), isin, score, sector?]. Entry at close of d + entry_lag sessions.
    Exit: after `hold` sessions, or close <= entry*(1-stop), or close <= peak*(1-trail). Equal weight 1/max_pos of equity
    at entry (cash otherwise). exposure: Series of max fraction invested by date (regime). Returns dict with equity curve + trades."""
    P = panel(); C = P['c']; dates = P['dates']
    cv = C.values; col = {k: i for i, k in enumerate(C.columns)}
    sig = signals.copy(); sig = sig[sig['isin'].isin(col)]
    sig['ei'] = [int(dates.searchsorted(pd.Timestamp(d).normalize(), side='left')) + entry_lag for d in sig.d]
    sig = sig[sig.ei < len(dates)]
    by_day = {k: g.sort_values(rank_col, ascending=False) for k, g in sig.groupby('ei')}
    s_i = dates.searchsorted(pd.Timestamp(start)) if start else 0
    e_i = dates.searchsorted(pd.Timestamp(end)) if end else len(dates) - 1
    cash = 1.0; pos = {}; eq = []; trades = []
    exp_v = exposure.reindex(dates).ffill().fillna(1).values if exposure is not None else None
    for i in range(s_i, e_i + 1):
        px = cv[i]
        # mark + exits
        for isin in list(pos):
            p = pos[isin]; c_ = px[col[isin]]
            if not np.isfinite(c_): continue
            p['last'] = c_; p['peak'] = max(p['peak'], c_)
            why = None
            if i - p['ei'] >= hold: why = 'time'
            elif stop and c_ <= p['entry'] * (1 - stop): why = 'stop'
            elif trail and c_ <= p['peak'] * (1 - trail): why = 'trail'
            if why:
                val = p['sh'] * c_ * (1 - cost); cash += val
                trades.append(dict(isin=isin, ed=dates[p['ei']], xd=dates[i], ret=c_ / p['entry'] * (1 - cost) / (1 + cost) - 1, why=why,
                                   days=i - p['ei'], sector=p.get('sector'), score=p['score']))
                del pos[isin]
        equity = cash + sum(p['sh'] * p['last'] for p in pos.values())
        # entries
        if i in by_day:
            cap = exp_v[i] if exp_v is not None else 1.0
            for _, s in by_day[i].iterrows():
                if len(pos) >= max_pos: break
                if s['isin'] in pos: continue
                c_ = px[col[s['isin']]]
                if not np.isfinite(c_) or c_ < min_price: continue
                invested = equity - cash
                if invested + equity / max_pos > cap * equity + 1e-9: break
                if sector_cap and 'sector' in s and sum(1 for p in pos.values() if p.get('sector') == s.sector) >= sector_cap: continue
                amt = min(equity / max_pos, cash)
                if amt <= equity / max_pos * 0.5: break
                cash -= amt; pos[s['isin']] = dict(ei=i, entry=c_, peak=c_, last=c_, sh=amt * (1 - cost) / c_, score=s[rank_col], sector=s.get('sector'))
        equity = cash + sum(p['sh'] * p['last'] for p in pos.values())
        eq.append((dates[i], equity, len(pos)))
    E = pd.DataFrame(eq, columns=['d', 'equity', 'n']).set_index('d')
    return dict(eq=E, trades=pd.DataFrame(trades))

def stats(res, bench=True, label=''):
    E = res['eq']; T = res['trades']; P = panel()
    r = E.equity.pct_change().fillna(0); yrs = len(E) / 248
    cagr = (E.equity.iloc[-1] / E.equity.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    dd = (E.equity / E.equity.cummax() - 1).min()
    sh = r.mean() / r.std() * np.sqrt(248) if r.std() > 0 else np.nan
    m = P['mkt'].reindex(E.index); mc = (m.iloc[-1] / m.iloc[0]) ** (1 / yrs) - 1
    mdd = (m / m.cummax() - 1).min()
    out = dict(label=label, cagr=round(cagr * 100, 1), mkt_cagr=round(mc * 100, 1), maxdd=round(dd * 100, 1), mkt_dd=round(mdd * 100, 1),
               sharpe=round(sh, 2), trades=len(T), win=round((T.ret > 0).mean() * 100, 1) if len(T) else None,
               avg=round(T.ret.mean() * 100, 2) if len(T) else None, avg_win=round(T.ret[T.ret > 0].mean() * 100, 1) if len(T) else None,
               avg_loss=round(T.ret[T.ret <= 0].mean() * 100, 1) if len(T) else None, exposure=round(E.n.mean(), 1))
    return out

def yearly(res):
    E = res['eq'].equity; P = panel(); m = P['mkt'].reindex(E.index)
    y = E.groupby(E.index.year).agg(['first', 'last']); my = m.groupby(m.index.year).agg(['first', 'last'])
    return pd.DataFrame({'strat': ((y['last'] / y['first'] - 1) * 100).round(1), 'mkt': ((my['last'] / my['first'] - 1) * 100).round(1)})

def cohort(signals, hold=60, stop=None, trail=None, cost=0.003, start=None, end=None, exposure=None, entry_lag=1, cap=None):
    """Equal-weight portfolio of ALL active signals (no slot limit unless cap). Each signal enters at close of
    (signal day + entry_lag), exits after `hold` sessions or on stop/trail (close-based). Daily return = mean of active
    position returns; idle days earn 0. exposure (0..1, known the day before) scales the whole book.
    cap: if set, at most `cap` positions open (new signals ranked by 'score' fill free slots)."""
    P = panel(); C = P['c']; dates = P['dates']; cv = C.values; col = {k: i for i, k in enumerate(C.columns)}
    sig = signals[signals['isin'].isin(col)].copy()
    sig['ei'] = [int(dates.searchsorted(pd.Timestamp(d).normalize(), side='left')) + entry_lag for d in sig.d]
    sig = sig[sig.ei < len(dates)].sort_values(['ei', 'score'], ascending=[True, False])
    s_i = dates.searchsorted(pd.Timestamp(start)) if start else 0
    e_i = dates.searchsorted(pd.Timestamp(end), side='right') - 1 if end else len(dates) - 1
    by_day = {k: g for k, g in sig.groupby('ei')}
    ex = exposure.reindex(dates).ffill().fillna(1).values if exposure is not None else np.ones(len(dates))
    act = {}; daily = []; trades = []
    for i in range(s_i, e_i + 1):
        px = cv[i]; rets = []; n_tr = 0
        for k in list(act):
            p = act[k]; c_ = px[p['ci']]
            if not np.isfinite(c_): rets.append(0.0); continue
            rets.append(c_ / p['last'] - 1); p['last'] = c_; p['peak'] = max(p['peak'], c_)
            why = None
            if i - p['ei'] >= hold: why = 'time'
            elif stop and c_ <= p['entry'] * (1 - stop): why = 'stop'
            elif trail and c_ <= p['peak'] * (1 - trail): why = 'trail'
            if why:
                trades.append(dict(isin=p['isin'], ed=dates[p['ei']], xd=dates[i], ret=c_ / p['entry'] - 1 - 2 * cost, why=why, days=i - p['ei'], score=p['score']))
                del act[k]; n_tr += 1
        n_before = max(len(rets), 1)
        if i in by_day:
            for _, s in by_day[i].iterrows():
                if cap and len(act) >= cap: break
                ci = col[s['isin']]; c_ = px[ci]
                if not np.isfinite(c_) or c_ < 20 or s['isin'] in {p['isin'] for p in act.values()}: continue
                act[(s['isin'], i)] = dict(isin=s['isin'], ci=ci, ei=i, entry=c_, last=c_, peak=c_, score=s['score']); n_tr += 1
        r = (np.mean(rets) if rets else 0.0) - (n_tr * cost / max(len(act), n_before) if (rets or act) else 0)
        daily.append((dates[i], r * ex[i] if (rets or act) else 0.0, len(act)))
    D = pd.DataFrame(daily, columns=['d', 'r', 'n']).set_index('d'); D['equity'] = (1 + D.r).cumprod()
    return dict(eq=D, trades=pd.DataFrame(trades))
