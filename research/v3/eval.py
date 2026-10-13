import sys,os; sys.path.insert(0,os.path.dirname(__file__)); import rs2, strat, pandas as pd, numpy as np
PER={'A 2022H2-23':('2022-07-01','2023-12-31'),'B 2024':('2024-01-01','2024-12-31'),'C 2025-26':('2025-01-01',None)}
def st(res):
    E=res['eq']; T=res['trades']; P=rs2.panel(); r=E.r; yrs=len(E)/248
    cagr=E.equity.iloc[-1]**(1/yrs)-1; dd=(E.equity/E.equity.cummax()-1).min(); sh=r.mean()/r.std()*np.sqrt(248) if r.std()>0 else np.nan
    m=P['mkt'].reindex(E.index); mc=(m.iloc[-1]/m.iloc[0])**(1/yrs)-1
    return dict(cagr=round(cagr*100,1),mkt=round(mc*100,1),dd=round(dd*100,1),sharpe=round(sh,2),n=len(T),win=round((T.ret>0).mean()*100,1) if len(T) else None,
                avg=round(T.ret.mean()*100,2) if len(T) else None,pos=round(E.n.mean(),1))
def grid(ev, cfgs, periods=PER, **kw):
    rows=[]
    for name,cfg in cfgs.items():
        c=dict(kw); c.update(cfg)
        e=ev.copy()
        if c.pop('min_mcap',500): e=e[e.mcap_pit>=500]
        f=c.pop('filt',None)
        if f is not None: e=e[f(e)]
        top=c.pop('top',None)
        if top: e=e[e.groupby('qn').score.rank(pct=True)>=1-top]
        rule=c.pop('rule',None); expo=strat.exposure(rule)
        for pn,(s,en) in periods.items():
            r=rs2.cohort(e[['d','isin','score']],start=s,end=en,exposure=expo,**c)
            row={'cfg':name,'per':pn}; row.update(st(r)); rows.append(row)
    return pd.DataFrame(rows)
