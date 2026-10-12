import json,urllib.request,os,sys,time
S=os.environ.get('CT_SCRATCH', '/tmp/ct-scratch')
A=open(f'{S}/secrets/bp_anon').read().strip(); K=open(f'{S}/secrets/ct_feed_key').read().strip()
U='https://wmmcgeycoacxdvdraewh.supabase.co/rest/v1/rpc/'
def rpc(fn,body):
    r=urllib.request.Request(U+fn,data=json.dumps(body).encode(),headers={'apikey':A,'Authorization':'Bearer '+A,'Content-Type':'application/json'})
    for i in range(5):
        try: return json.loads(urllib.request.urlopen(r,timeout=120).read())
        except Exception as e: print('retry',fn,e,flush=True); time.sleep(5*(i+1))
    raise SystemExit('feed failed')
meta=rpc('ct_feed_meta',{'p_key':K}); json.dump(meta,open(f'{S}/data/px/meta.json','w'))
print('meta', {k:(len(v) if isinstance(v,(list,dict)) else v) for k,v in meta.items()},flush=True)
after=''; out=open(f'{S}/data/px/prices.jsonl','w'); n=0
while True:
    rows=rpc('ct_feed_prices',{'p_key':K,'p_after':after,'p_n':150})
    if not rows: break
    for r in rows: out.write(json.dumps(r)+'\n')
    n+=len(rows); after=rows[-1]['isin']
print('isins',n)
