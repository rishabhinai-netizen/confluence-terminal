import json,glob,urllib.request,time,datetime,sys
S=__import__('os').environ.get('CT_WORK', './work')
URL='https://ybdqdpwfhgngggaomvqq.supabase.co/functions/v1/ct-ingest'
A=open(f'{S}/secrets/ct_anon').read().strip(); K=open(f'{S}/secrets/ingest_key').read().strip()
def post(table,rows,oc,chunk=2000):
    for i in range(0,len(rows),chunk):
        body=json.dumps({'table':table,'rows':rows[i:i+chunk],'on_conflict':oc}).encode()
        for a in range(5):
            try:
                j=json.loads(urllib.request.urlopen(urllib.request.Request(URL,data=body,method='POST',headers={'Authorization':'Bearer '+A,'x-ct-key':K,'Content-Type':'application/json'}),timeout=150).read())
                assert j.get('ok'),j; break
            except Exception as e: print('retry',table,i,str(e)[:150],flush=True); time.sleep(5*(a+1))
        else: sys.exit('fail '+table)
def iso(ms): return datetime.datetime.fromtimestamp(ms/1000,datetime.timezone.utc).isoformat() if ms else None
what=sys.argv[1:]
if 'res' in what:
    rows={}
    for f in glob.glob(f'{S}/data/es/results_Q*.jsonl'):
        for l in open(f):
            r=json.loads(l)
            if not r.get('id') or not r.get('isin'): continue
            rows[r['id']]=dict(id=r['id'],isin=r['isin'],symbol=r.get('symbol'),name=r.get('companyName'),sector=r.get('companySector'),q=r.get('quarter'),fy=r.get('fy'),
              qn=(r.get('fy') or 0)*4+(r.get('quarter') or 0),ts=iso(r.get('resultAnnouncementEpoch')),revenue=r.get('revenue'),pat=r.get('profitAfterTax'),eps=r.get('dilutedEPS'),
              rev_yoy=r.get('revenueYoyGrowth'),pat_yoy=r.get('patYoyGrowth'),eps_yoy=r.get('epsYoyGrowth'),opm=r.get('opm'),opm_bps=r.get('opmYoyBps'),
              verdict=r.get('resultVerdict'),bsh=r.get('balanceSheetHealth'),rtype=r.get('type'),mcap_now=r.get('marketCap'),pdf=r.get('pdfUrl'))
    post('ct_res',list(rows.values()),'id'); print('ct_res',len(rows),flush=True)
if 'cc' in what:
    rows={}
    for f in glob.glob(f'{S}/data/es/concalls_Q*.jsonl'):
        for l in open(f):
            r=json.loads(l)
            if not r.get('isin'): continue
            k=(r['isin'],(r.get('year') or 0)*4+(r.get('quarter') or 0)); rows[k]=dict(isin=k[0],qn=k[1],guid=r.get('guidanceRevision'),tone=r.get('managementTone'))
    post('ct_concall_lite',list(rows.values()),'isin,qn'); print('cc',len(rows),flush=True)
if 'px' in what:
    rows=[]
    for l in open(f'{S}/data/px/hist.jsonl'):
        r=json.loads(l)
        for d,c,lo in zip(r['d'],r['c'],r['l']):
            if d>='2024-01-01' and d<'2025-01-10': rows.append(dict(isin=r['isin'],d=d,c=c,l=lo))
    print('px rows',len(rows),flush=True)
    post('ct_prices',rows,'isin,d',chunk=5000); print('px done',flush=True)
