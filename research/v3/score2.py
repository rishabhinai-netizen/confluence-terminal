# Point-in-time scoring: each feature is ranked against the PREVIOUS reporting season's distribution (fully known
# before the current season starts), never against companies that report later in the same season.
import numpy as np, pandas as pd
GROUPS={'growth':['revenueYoyGrowth','patYoyGrowth','sue_p','opmYoyBps'],'trend':['above200','off_hi','sma200_up','run120'],'react':['react_x']}
W={'growth':2,'trend':1,'react':1}
def pit_rank(ev, col):
    out=pd.Series(np.nan,index=ev.index)
    for q,g in ev.groupby('qn'):
        ref=ev.loc[ev.qn==q-1,col].dropna().values
        if len(ref)<200: ref=ev.loc[(ev.qn>=q-2)&(ev.qn<q),col].dropna().values
        if len(ref)<100: continue
        ref=np.sort(ref)
        v=g[col].values; m=np.isfinite(v)
        r=np.full(len(v),np.nan); r[m]=np.searchsorted(ref,v[m],side='right')/len(ref)
        out.loc[g.index]=r
    return out
def add_scores(ev, groups=GROUPS, w=W, ref_ev=None):
    ev=ev.copy(); ev['sue_p']=ev.sue_p.clip(-20,20)
    for g,cols in groups.items():
        ev['g_'+g]=pd.concat([pit_rank(ev,c) for c in cols],axis=1).mean(axis=1)
    ev['score']=sum(ev['g_'+g].fillna(0.5)*w[g] for g in groups)/sum(w.values())
    # threshold also from the previous season: pr = score percentile vs previous season's scores
    ev['pr']=pit_rank(ev,'score')
    return ev
