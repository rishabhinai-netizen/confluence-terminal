import sys,os; sys.path.insert(0,os.path.dirname(__file__)); import rs2, score, regime, pandas as pd, numpy as np
def events_scored():
    ev=score.add_scores(pd.read_pickle(rs2.S+'/data/feat_ev.pkl'))
    P=rs2.panel(); ev['d']=P['dates'][ev.ei.clip(upper=len(P['dates'])-1)]
    ev['sector']=ev.companySector.fillna('?')
    return ev
def exposure(rule):
    if rule is None: return None
    sig,B=regime.signals(); P=rs2.panel(); m=P['mkt']
    if rule=='vote3':
        v=(sig['mkt>sma100'].astype(int)+sig['br50>50'].astype(int)+sig['hi>lo'].astype(int))/3
        return v.shift(1).fillna(1)
    return sig[rule].astype(float).shift(1).fillna(1)
def run(ev, filt=None, top=None, max_pos=10, hold=60, stop=None, trail=None, cost=0.003, start='2022-07-01', end=None, rule=None, sector_cap=None, min_mcap=500):
    e=ev.copy()
    if min_mcap: e=e[e.mcap_pit>=min_mcap]
    if filt is not None: e=e[filt(e)]
    if top: e=e[e.groupby('qn').score.rank(pct=True)>=1-top]
    sig=e[['d','isin','score','sector']]
    res=rs2.backtest(sig,max_pos=max_pos,hold=hold,stop=stop,trail=trail,cost=cost,start=start,end=end,exposure=exposure(rule),sector_cap=sector_cap)
    return res
