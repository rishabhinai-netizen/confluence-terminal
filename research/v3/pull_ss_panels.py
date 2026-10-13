# Point-in-time StockScans panels (mcap>=500) at month-end snapshot dates. Checkpoint per page. Output data/ssp/<type>.jsonl
import sys,os,json,time,datetime
sys.path.insert(0,os.path.dirname(__file__))
from api import ss,S
OUT=f'{S}/data/ssp'; CK=f'{OUT}/_ck.json'; LOG=open(f'{OUT}/_log.txt','a')
def log(*a): LOG.write(time.strftime('%H:%M:%S ')+' '.join(map(str,a))+'\n'); LOG.flush()
ck=json.load(open(CK)) if os.path.exists(CK) else {}
dates=sorted(json.load(open(f'{S}/ss/hist_dates.json'))['dates'])
me=[d for i,d in enumerate(dates) if i==len(dates)-1 or dates[i+1][:7]!=d[:7]]
order=sorted(me,reverse=True)
TYPES=sys.argv[1].split(',') if len(sys.argv)>1 else ['Holdings','Ratios','Valuation','Scores']
scan={'scanId':'','scanName':'x','industry':[],'index':[],'tags':[],'filters':[{'left':'Market Capitalization','sign':'>=','right':'500'}]}
log('plan',order,TYPES)
for d in order:
    for rt in TYPES:
        key=f'{d}|{rt}'; st=ck.get(key,{'off':0})
        if st.get('done'): continue
        f=open(f'{OUT}/{rt.replace("/","_").replace(" ","_")}.jsonl','a')
        while True:
            wait=60
            while True:
                c,j=ss('/api/scans/stock/run',{'ratiosType':rt,'timePeriod':d,'scan':scan,'watchlistIds':[],'order':'desc','orderBy':'Market Capitalization','offset':st['off']},ref='https://www.stockscans.in/stock-scans')
                if c==200 and isinstance(j,dict) and 'table' in j: break
                if c in (401,403): log('AUTH FAIL'); sys.exit(1)
                log('HTTP',c,str(j)[:100],'sleep',wait); time.sleep(wait); wait=min(wait*2,600)
            hdr=j['table'][0]
            for r in j['table'][1:]: f.write(json.dumps({'d':d,'row':dict(zip(hdr,r))})+'\n')
            f.flush()
            if not j.get('end') or j['end']>=j.get('total',0): st['done']=True
            else: st['off']=j['end']
            ck[key]=st; json.dump(ck,open(CK,'w'))
            if st.get('done'): break
            time.sleep(1.5)
        log('done',key,j.get('total'))
log('ALL DONE')
