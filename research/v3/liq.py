import sys,os; sys.path.insert(0,os.path.dirname(__file__)); import rs2, pandas as pd, numpy as np
def turnover():
    cache=rs2.S+'/data/turn.pkl'
    if os.path.exists(cache): return pd.read_pickle(cache)
    P=rs2.panel(); t=(P['c']*P['v']/1e7).rolling(20,min_periods=10).median(); t.to_pickle(cache); return t
def tradeable(ev, min_mcap=1000, min_turn=5):
    t=turnover(); P=rs2.panel(); col={k:i for i,k in enumerate(P['c'].columns)}
    tv=np.array([t.iat[min(i,len(t)-1), col[s]] if s in col else np.nan for s,i in zip(ev['isin'],ev.ei)])
    ev=ev.copy(); ev['turn20']=tv
    ok=(ev.mcap_pit>=min_mcap)&(np.where(np.isfinite(tv), tv>=min_turn, True))
    return ev[ok]
