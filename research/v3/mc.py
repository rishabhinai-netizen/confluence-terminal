import sys,os; sys.path.insert(0,os.path.dirname(__file__)); import strat, liq, score, eval as E, rs2, pandas as pd, numpy as np
P=rs2.panel(); dates=P['dates']
def load(w=dict(growth=2,trend=1,react=1)):
    base=pd.read_pickle(rs2.S+'/data/feat_ev.pkl')
    ev=score.add_scores(base,{'growth':score.GROUPS['growth'],'trend':score.GROUPS['trend'],'react':['react_x']},w)
    ev['d']=dates[ev.ei.clip(upper=len(dates)-1)]; ev=liq.tradeable(ev)
    ev['pr']=ev.groupby('qn').score.rank(pct=True); return ev
def sims(ev, top=0.1, cap=15, hold=60, rule='vote3', n=30, win=10, start='2022-07-01', end=None, filt=None, seed=0, periods=None):
    rng=np.random.default_rng(seed); e0=ev[ev.pr>=1-top]
    if filt is not None: e0=e0[filt(e0)]
    expo=strat.exposure(rule); out=[]
    for k in range(n):
        e=e0.copy(); delay=rng.integers(0,win,len(e)); e['d']=dates[(e.ei+delay).clip(upper=len(dates)-1)]
        e['score']=e.score+rng.normal(0,0.02,len(e))
        if periods:
            for pn,(s,en) in periods.items():
                r=rs2.cohort(e[['d','isin','score']],hold=hold,start=s,end=en,cap=cap,exposure=expo); x=E.st(r); x['per']=pn; x['sim']=k; out.append(x)
        else:
            r=rs2.cohort(e[['d','isin','score']],hold=hold,start=start,end=end,cap=cap,exposure=expo); x=E.st(r); x['sim']=k; out.append(x)
    return pd.DataFrame(out)
def summ(df):
    g=df.groupby('per') if 'per' in df else [('all',df)]
    rows=[]
    for p,d in g:
        rows.append(dict(per=p,cagr_p10=round(d.cagr.quantile(.1),1),cagr_med=round(d.cagr.median(),1),cagr_p90=round(d.cagr.quantile(.9),1),
                         dd_med=round(d.dd.median(),1),dd_worst=round(d.dd.min(),1),sharpe_med=round(d.sharpe.median(),2),mkt=d.mkt.iloc[0]))
    return pd.DataFrame(rows)
