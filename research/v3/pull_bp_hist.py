import json,urllib.request,time
S=__import__('os').environ.get('CT_WORK', './work')
A=open(f'{S}/secrets/bp_anon').read().strip(); K=open(f'{S}/secrets/ct_feed_key').read().strip()
def rpc(fn,body):
    r=urllib.request.Request('https://wmmcgeycoacxdvdraewh.supabase.co/rest/v1/rpc/'+fn,data=json.dumps(body).encode(),headers={'apikey':A,'Authorization':'Bearer '+A,'Content-Type':'application/json'})
    for i in range(6):
        try: return json.loads(urllib.request.urlopen(r,timeout=120).read())
        except Exception as e: print('retry',e,flush=True); time.sleep(4*(i+1))
    raise SystemExit('fail')
after=''; out=open(f'{S}/data/px/hist.jsonl','w'); n=0
while True:
    rows=rpc('ct_feed_hist',{'p_key':K,'p_after':after,'p_n':40,'p_since':'2018-01-01'})
    if not rows: break
    for r in rows: out.write(json.dumps(r)+'\n')
    n+=len(rows); after=rows[-1]['isin']
print('hist isins',n)
