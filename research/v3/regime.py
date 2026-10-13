import sys,json,os; sys.path.insert(0,os.path.dirname(__file__)); import rs2, pandas as pd, numpy as np
def breadth():
    b=json.load(open(rs2.S+'/ss/breadth.json'))['indicators']
    return pd.DataFrame({k:pd.Series({pd.Timestamp(x[0]):x[3] for x in v}) for k,v in b.items()}).sort_index()
def signals():
    P=rs2.panel(); m=P['mkt']; B=breadth().reindex(m.index).ffill()
    sig={}
    for n in (50,100,200): sig[f'mkt>sma{n}']=m>m.rolling(n).mean()
    sig['br50>50']=B.p_a_ema_50d>50; sig['br200>50']=B.p_a_ema_200d>50; sig['br20>50']=B.p_a_ema_20d>50
    sig['hi>lo']=B.p_l_5_52wh>B.p_l_5_52wl
    sig['br50 rising']=B.p_a_ema_50d>B.p_a_ema_50d.rolling(10).mean()
    sig['mkt>sma50 & br200>40']=(m>m.rolling(50).mean())&(B.p_a_ema_200d>40)
    sig['mkt>sma100 or br50>60']=(m>m.rolling(100).mean())|(B.p_a_ema_50d>60)
    sig['mkt>sma50 or br50 rising']=(m>m.rolling(50).mean())|(B.p_a_ema_50d>B.p_a_ema_50d.rolling(10).mean())
    return {k:v.astype(bool) for k,v in sig.items()}, B
