# Strategy league table: legend-inspired rules tested on identical plumbing.
# Universe: tradeable results (mcap_pit >= 1000 cr, turnover >= 5 cr where volume exists), PIT-scored, 2023-01-01 -> latest.
# Each pool: entries within 10 sessions of the first post-result close, 15 slots, 60-session hold, 0.3%/side,
# new buys sized by the 3-vote market gauge. Order inside a pool is random (median of N runs) so we measure the POOL, not a ranking,
# except 'Composite (ranked)' which uses the composite score order.
import sys, os, glob, json, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import sim2, strat, rs2
S = rs2.S; dates = sim2.dates
e = pd.read_pickle(f'{S}/data/ev_pit.pkl').copy()
# concall guidance / tone
cc = {}
for f in glob.glob(f'{S}/data/es/concalls_Q*.jsonl'):
    for line in open(f):
        r = json.loads(line)
        if not r.get('isin'): continue
        cc[(r['isin'], (r.get('year') or 0) * 4 + (r.get('quarter') or 0))] = (r.get('guidanceRevision'), r.get('managementTone'))
e['guid'] = [cc.get((a, b), (None, None))[0] for a, b in zip(e['isin'], e['qn'])]
e['tone'] = [cc.get((a, b), (None, None))[1] for a, b in zip(e['isin'], e['qn'])]
# trailing-4Q EPS for P/E (point in time: only quarters already reported)
allr = rs2.results_events()
key = allr.drop_duplicates(['isin', 'qn']).set_index(['isin', 'qn'])['dilutedEPS']
ttm = sum(key.reindex(list(zip(e['isin'], e.qn - k))).values for k in range(4))
e['pe'] = np.where(ttm > 0, e.cpre / ttm, np.nan)
e['peg'] = np.where((e.pe > 0) & (e.patYoyGrowth > 0), e.pe / e.patYoyGrowth, np.nan)
e = e[e.ts >= '2022-10-01']
ex = strat.exposure('vote3')

def prev_q(col, q):  # threshold = quantile of the PREVIOUS season (no look-ahead), same convention as the composite
    t = e.groupby('qn')[col].quantile(q); t.index = t.index + 1
    return e.qn.map(t).values

pools = {
  'All tradeable results (baseline)': np.ones(len(e), bool),
  'PEAD - biggest earnings surprise (Bernard & Thomas)': (e.sue_p.values >= prev_q('sue_p', 0.9)),
  'Episodic pivot - biggest result-day reaction': (e.react_x.values >= prev_q('react_x', 0.9)),
  'CAN SLIM core (O\'Neil): PAT >= 25%, revenue >= 20%, within 15% of high': ((e.patYoyGrowth >= 25) & (e.revenueYoyGrowth >= 20) & (e.off_hi >= -0.15)).values,
  'Trend template + earnings (Minervini)': ((e.above200 > 0) & (e.sma200_up > 0) & (e.off_hi >= -0.25) & (e.above_lo >= 0.3) & (e.patYoyGrowth >= 20)).values,
  'Relative strength - top 10% 6-month run (Jegadeesh-Titman)': (e.run120.values >= prev_q('run120', 0.9)),
  'GARP (Lynch): PEG < 1, PAT growth 15-60%': ((e.peg < 1) & (e.patYoyGrowth.between(15, 60))).values,
  'Cheap: lowest 20% P/E (Graham-style value)': (e.pe.values <= prev_q('pe', 0.2)),
  'Consistent compounder: PAT>15% & revenue>10% for 3 quarters': ((e.pat_streak >= 3) & (e.rev_streak >= 3)).values,
  'Management raised guidance (concall)': (e.guid == 'RAISED').values,
  'Management cut guidance (concall)': (e.guid == 'CUT').values,
  'Platform label: PEAD "Fantastic"': (e.peadLabel == 'Fantastic').values,
  'Composite top 10% (growth x2 + trend + reaction)': ((e.pr >= 0.9) & (e.guid != 'CUT') & (e.balanceSheetHealth != 'STRESSED')).values,
}

def signals(mask, score):
    s = e[mask]
    rows = [(i, dates[int(j) + k], sc) for i, j, sc in zip(s['isin'], s['ei'], score[mask]) for k in range(10) if int(j) + k < len(dates)]
    return pd.DataFrame(rows, columns=['isin', 'd', 'score'])

def stats(D, start):
    eq = D.equity; yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    y = eq.resample('YE').last(); prev = pd.concat([pd.Series([1.0]), y.iloc[:-1]]).values
    return dict(cagr=eq.iloc[-1] ** (1 / yrs) - 1, dd=(eq / eq.cummax() - 1).min(),
                yearly={str(k.year): v for k, v in zip(y.index, y.values / prev - 1)}, avg_n=D.n.mean())

def run_pool(name, mask, n=int(os.environ.get('NRUN', 20)), start='2023-01-01', ranked=False, expo=ex):
    rng = np.random.default_rng(7)
    out = []
    for k in range(1 if ranked else n):
        sc = e.score.values if ranked else rng.random(len(e))
        R = sim2.run(signals(mask, sc), e, start=start, exposure=expo, regime_mode='scale')
        out.append(stats(R['eq'], start))
    med = lambda f: float(np.median([o[f] for o in out]))
    yrs = sorted(out[0]['yearly'])
    return dict(name=name, events=int(mask.sum()), x60_med=float(np.nanmedian(e.loc[mask, 'x60_l1'])), x60_mean=float(np.nanmean(e.loc[mask, 'x60_l1'].clip(-1, 3))),
                hit60=float((e.loc[mask, 'x60_l1'] > 0).mean()), cagr=med('cagr'), dd=med('dd'),
                cagr_p10=float(np.percentile([o['cagr'] for o in out], 10)), cagr_p90=float(np.percentile([o['cagr'] for o in out], 90)),
                yearly={y: float(np.median([o['yearly'][y] for o in out])) for y in yrs}, avg_n=med('avg_n'))

if __name__ == '__main__':
    res = []
    for name, m in pools.items():
        r = run_pool(name, m); res.append(r)
        print(f"{r['cagr']*100:6.1f}% dd {r['dd']*100:6.1f}%  n={r['events']:5d} x60med {r['x60_med']*100:5.1f}  {name}", flush=True)
    m = pools['Composite top 10% (growth x2 + trend + reaction)']
    r = run_pool('Composite top 10%, ranked by score (the model)', m, ranked=True); res.append(r)
    print(f"{r['cagr']*100:6.1f}% dd {r['dd']*100:6.1f}%  model ranked", flush=True)
    r = run_pool('The model without the market gauge', m, ranked=True, expo=None); res.append(r)
    print(f"{r['cagr']*100:6.1f}% dd {r['dd']*100:6.1f}%  model no gauge", flush=True)
    r = run_pool('Baseline without the market gauge', pools['All tradeable results (baseline)'], expo=None); res.append(r)
    print(f"{r['cagr']*100:6.1f}% dd {r['dd']*100:6.1f}%  baseline no gauge", flush=True)
    json.dump(res, open(f'{S}/data/league.json', 'w'), indent=1)
