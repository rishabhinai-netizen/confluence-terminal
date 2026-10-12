# StockScans point-in-time scan membership puller. Checkpoints every request. Output data/ss/scanhist.jsonl
import sys,os,json,time,datetime
sys.path.insert(0,os.path.dirname(__file__))
from api import ss,S
OUT=f'{S}/data/ss'; CK=f'{OUT}/_scan_ck.json'; LOG=open(f'{OUT}/_scan_log.txt','a')
def log(*a): LOG.write(time.strftime('%H:%M:%S ')+' '.join(map(str,a))+'\n'); LOG.flush()
ck=json.load(open(CK)) if os.path.exists(CK) else {'done':[]}
done=set(ck['done'])
scans=[s for g in json.load(open(f'{S}/ss/scans_stock_popular.json'))['scans'] for s in g]
dates=json.load(open(f'{S}/ss/hist_dates.json'))['dates']
# month-end dates first, then week-ends, newest first within each tier
ds=sorted(dates)
monthly=[d for i,d in enumerate(ds) if i==len(ds)-1 or ds[i+1][:7]!=d[:7]]
weekly=[d for i,d in enumerate(ds) if (i==len(ds)-1 or datetime.date.fromisoformat(ds[i+1]).isocalendar()[1]!=datetime.date.fromisoformat(d).isocalendar()[1]) and d not in monthly]
order=sorted(monthly,reverse=True)+sorted(weekly,reverse=True)
log('plan',len(monthly),'monthly',len(weekly),'weekly',len(scans),'scans')
out=open(f'{OUT}/scanhist.jsonl','a'); nreq=0; t0=time.time()
for d in order:
    for s in scans:
        key=f"{d}|{s['scanId']}"
        if key in done: continue
        rows=[]; off=0; ok=True
        while True:
            body={'ratiosType':'Quick','timePeriod':d,'scan':s,'watchlistIds':[],'order':'desc','orderBy':'Market Capitalization','offset':off}
            wait=60
            while True:
                c,j=ss('/api/scans/stock/run',body,ref='https://www.stockscans.in/stock-scans'); nreq+=1
                if c==200 and isinstance(j,dict) and 'table' in j: break
                log('HTTP',c,str(j)[:150],'after',nreq,'req',int(time.time()-t0),'s; sleeping',wait)
                if c in (401,403): log('AUTH FAIL - stop'); sys.exit(1)
                if c==402 or (c==400): ok=False; break
                time.sleep(wait); wait=min(wait*2,900)
            if not ok: break
            tab=j['table']; hdr=tab[0]; ci=hdr.index('companyId')
            for r in tab[1:]: rows.append(r[ci])
            tot=j.get('total')
            if not j.get('end') or j['end']>=j.get('total',0) or len(rows)>=200: break
            off=j['end']; time.sleep(1.2)
        out.write(json.dumps({'date':d,'scan':s['scanId'],'n':len(rows),'total':tot if ok else None,'ids':rows,'ok':ok})+'\n'); out.flush()
        done.add(key); ck['done']=list(done); json.dump(ck,open(CK,'w'))
        time.sleep(1.2)
    log('date done',d,'req',nreq)
log('ALL DONE')
