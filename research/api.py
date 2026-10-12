import json, sys, os, time, urllib.request, urllib.error
S=os.environ.get('CT_SCRATCH', '/tmp/ct-scratch')
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36 Edg/155.0.0.0'
def ck(n): return open(f'{S}/secrets/{n}_cookie').read().strip()
def ss(path, body=None, method=None, ref='https://www.stockscans.in/concall-scans', raw=False):
    url = path if path.startswith('http') else 'https://www.stockscans.in'+path
    h={'accept':'application/json','content-type':'application/json','cookie':ck('ss'),'user-agent':UA,
       'referer':ref,'origin':'https://www.stockscans.in','x-sync-source':'aqsa4985mv5fk5yp'}
    data=None
    if body is not None:
        data=json.dumps(body).encode(); h['x-sync-skip']='1'
    req=urllib.request.Request(url,data=data,headers=h,method=method or ('POST' if data else 'GET'))
    try:
        r=urllib.request.urlopen(req,timeout=60); bb=r.read(); code=r.status
        if r.headers.get('Content-Encoding')=='gzip' or bb[:2]==b'\x1f\x8b':
            import gzip; bb=gzip.decompress(bb)
        t=bb.decode('utf-8','replace')
    except urllib.error.HTTPError as e:
        t=e.read().decode('utf-8','replace'); code=e.code
    if raw: return code,t
    try: return code,json.loads(t)
    except Exception: return code,t
def es(path, raw=False):
    url = path if path.startswith('http') else 'https://equisense.ai'+path
    h={'accept':'*/*','content-type':'application/json','cookie':ck('es'),'user-agent':UA,'referer':'https://equisense.ai/glance'}
    req=urllib.request.Request(url,headers=h)
    try:
        r=urllib.request.urlopen(req,timeout=60); bb=r.read(); code=r.status
        if r.headers.get('Content-Encoding')=='gzip' or bb[:2]==b'\x1f\x8b':
            import gzip; bb=gzip.decompress(bb)
        t=bb.decode('utf-8','replace')
    except urllib.error.HTTPError as e:
        t=e.read().decode('utf-8','replace'); code=e.code
    if raw: return code,t
    try: return code,json.loads(t)
    except Exception: return code,t
def shape(o,d=0,maxd=4):
    pad='  '*d
    if d>maxd: return pad+'...'
    if isinstance(o,dict):
        return '\n'.join(f'{pad}{k}: '+(type(v).__name__+(f'[{len(v)}]' if isinstance(v,(list,dict)) else '')+ ('' if isinstance(v,(list,dict)) else ' = '+repr(v)[:80]) )+('\n'+shape(v,d+1,maxd) if isinstance(v,(dict,list)) and v else '') for k,v in o.items())
    if isinstance(o,list) and o:
        return pad+f'[0] of {len(o)}:\n'+shape(o[0],d+1,maxd)
    return pad+repr(o)[:80]
