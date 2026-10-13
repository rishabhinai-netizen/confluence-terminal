# Slot-limited simulator with richer exits:
#  base hold H; 'confirm': at the stock's next results, extend by H if that result is good (pr>=keep_pr and react_x>-0.03), else exit;
#  'sma': exit when close < SMA(n) after min_days; regime exposure trims lowest-ranked names.
import sys,os; sys.path.insert(0,os.path.dirname(__file__)); import rs2, strat, numpy as np, pandas as pd
P=rs2.panel(); C=P['c']; dates=P['dates']; cv=C.values; COL={k:i for i,k in enumerate(C.columns)}
SMA={}
def sma(n):
    if n not in SMA: SMA[n]=C.rolling(n,min_periods=int(n*0.8)).mean().values
    return SMA[n]
def run(signals, allev, cap=15, hold=60, exit_mode='time', keep_pr=0.5, sma_n=50, min_days=10, max_hold=250, cost=0.003,
        start='2022-07-01', end=None, exposure=None, regime_mode='block', block_below=0.5):
    sig=signals[signals['isin'].isin(COL)].copy()
    sig['si']=[int(dates.searchsorted(pd.Timestamp(d).normalize(),side='left'))+1 for d in sig.d]   # execute next close
    by_day={k:g.sort_values('score',ascending=False) for k,g in sig.groupby('si')}
    # next-result lookup: for each isin, sorted (ei, pr, react_x)
    nxt={k:g.sort_values('ei')[['ei','pr','react_x']].values for k,g in allev.groupby('isin')}
    s_i=dates.searchsorted(pd.Timestamp(start)); e_i=dates.searchsorted(pd.Timestamp(end),side='right')-1 if end else len(dates)-1
    ex=exposure.reindex(dates).ffill().fillna(1).values if exposure is not None else np.ones(len(dates))
    S=sma(sma_n) if exit_mode=='sma' else None
    pos={}; daily=[]; trades=[]
    for i in range(s_i,e_i+1):
        px=cv[i]; rets=[]; ntr=0
        for k in list(pos):
            p=pos[k]; c_=px[COL[k]]
            if not np.isfinite(c_): rets.append(0.0); continue
            rets.append((c_/p['last']-1)*p.get('w',1.0)); p['last']=c_
            why=None; age=i-p['ei']
            if exit_mode=='confirm':
                # did a new result arrive (entry index of a later result == i)?
                arr=nxt.get(k)
                if arr is not None:
                    hit=arr[(arr[:,0]==i)]
                    if len(hit) and i>p['ei']+5:
                        if hit[0,1]>=keep_pr and hit[0,2]>-0.03: p['until']=i+hold
                        else: why='bad next result'
                if not why and i>=p['until']: why='time'
                if not why and age>=max_hold: why='max'
            elif exit_mode=='sma':
                if age>=min_days and np.isfinite(S[i,COL[k]]) and c_<S[i,COL[k]]: why='sma'
                elif age>=max_hold: why='max'
            else:
                if age>=hold: why='time'
            if why:
                trades.append(dict(isin=k,ed=dates[p['ei']],xd=dates[i],ret=c_/p['entry']-1-2*cost,why=why,days=age)); del pos[k]; ntr+=1
        nb=max(len(rets),1)
        lim=int(round(cap*ex[i])) if regime_mode=='trim' else cap
        if regime_mode=='block' and ex[i]<block_below: lim=len(pos)   # no new buys in a weak market; holdings run their course
        while regime_mode=='trim' and len(pos)>lim:   # regime trim: drop weakest score
            k=min(pos,key=lambda z:pos[z]['score']); p=pos.pop(k); c_=px[COL[k]]
            trades.append(dict(isin=k,ed=dates[p['ei']],xd=dates[i],ret=c_/p['entry']-1-2*cost,why='regime',days=i-p['ei'])); ntr+=1
        if i in by_day and not (regime_mode=='scale' and ex[i]<=0):   # scale mode: gauge 0 means no buys (no zero-weight placeholder positions)
            for _,s in by_day[i].iterrows():
                if len(pos)>=lim: break
                k=s['isin']
                if k in pos: continue
                c_=px[COL[k]]
                if not np.isfinite(c_) or c_<20: continue
                pos[k]=dict(ei=i,entry=c_,last=c_,score=s['score'],until=i+hold,w=(ex[i] if regime_mode=='scale' else 1.0)); ntr+=1
        r=(np.mean(rets)*(len(rets)/cap) if rets else 0.0)-ntr*cost/cap
        daily.append((dates[i],r,len(pos)))
    D=pd.DataFrame(daily,columns=['d','r','n']).set_index('d'); D['equity']=(1+D.r).cumprod()
    return dict(eq=D,trades=pd.DataFrame(trades),pos=pos)
