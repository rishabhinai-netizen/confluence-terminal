# EquiSense history puller with per-page checkpoints. Output: data/es/<dataset>.jsonl
import sys,os,json,time
sys.path.insert(0,os.path.dirname(__file__))
from api import es,S
OUT=f'{S}/data/es'; CK=f'{OUT}/_checkpoint.json'
ck=json.load(open(CK)) if os.path.exists(CK) else {}
def save(): json.dump(ck,open(CK,'w'))
def pull(name,url_tmpl,ps):
    key=name; page=ck.get(key,0)
    if page=='done': return
    f=open(f'{OUT}/{name}.jsonl','a')
    while True:
        for attempt in range(5):
            c,j=es(url_tmpl.format(page=page,ps=ps))
            if c==200 and isinstance(j,dict): break
            print(name,page,'HTTP',c,str(j)[:120],flush=True); time.sleep(10*(attempt+1))
        else:
            print('GIVEUP',name,page,flush=True); return
        for r in j.get('content',[]): f.write(json.dumps(r)+'\n')
        f.flush(); page+=1; ck[key]=page; save()
        if not j.get('hasNext'): ck[key]='done'; save(); print('DONE',name,j.get('totalElements'),flush=True); return
        time.sleep(0.25)
QS=[(2,2027),(1,2027),(4,2026),(3,2026),(2,2026),(1,2026),(4,2025)]
for q,fy in QS:
    pull(f'results_Q{q}FY{fy}','/api/v1/discover/results/glance?page={page}&pageSize={ps}&quarter='+f'{q}&fy={fy}',50)
    pull(f'concalls_Q{q}FY{fy}','/api/v1/concalls?page={page}&pageSize={ps}&quarter='+f'{q}&fy={fy}',100)
for src in ['BULK','BLOCK','INSIDER','SAST']:
    pull(f'smart_{src}','/api/v1/smart-money/recent?source='+src+'&days=400&page={page}&pageSize={ps}',100)
for kind in ['orders','capex','mna','open-offers','updates','preferential-issues','buybacks','rights-issues','product-launches']:
    pull(f'filings_{kind}','/api/v1/discover/filings/glance?kind='+kind+'&page={page}&pageSize={ps}',100)
print('ALL DONE',flush=True)
