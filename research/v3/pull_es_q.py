# parallel EquiSense quarter puller: python3 pull_es_q.py Q FY  (own checkpoint per quarter)
import sys,os,json,time
sys.path.insert(0,os.path.dirname(__file__))
from api import es,S
q,fy=int(sys.argv[1]),int(sys.argv[2]); OUT=f'{S}/data/es'
for name,tmpl,ps in [(f'results_Q{q}FY{fy}',f'/api/v1/discover/results/glance?page={{page}}&pageSize=50&quarter={q}&fy={fy}',50),
                     (f'concalls_Q{q}FY{fy}',f'/api/v1/concalls?page={{page}}&pageSize=100&quarter={q}&fy={fy}',100)]:
    CK=f'{OUT}/_ck_{name}.json'; page=json.load(open(CK))['page'] if os.path.exists(CK) else 0
    if page=='done': continue
    f=open(f'{OUT}/{name}.jsonl','a' if page else 'w')
    while True:
        c,j=es(tmpl.format(page=page))
        if c!=200 or not isinstance(j,dict): print(name,page,c,str(j)[:100],flush=True); time.sleep(10); continue
        for r in j.get('content',[]): f.write(json.dumps(r)+'\n')
        f.flush(); page+=1; json.dump({'page':page},open(CK,'w'))
        if not j.get('hasNext'): json.dump({'page':'done'},open(CK,'w')); print('DONE',name,j.get('totalElements'),flush=True); break
