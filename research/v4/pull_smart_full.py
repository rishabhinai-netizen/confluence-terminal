from api import es, S
import json
out = open(f'{S}/data/es/smart_full.jsonl', 'w'); n = 0
for src in ['BULK', 'BLOCK', 'INSIDER', 'SAST']:
    p = 1
    while True:
        c, j = es(f'/api/v1/smart-money/recent?source={src}&days=3000&page={p}&pageSize=100')
        if c != 200: print('err', src, p, c, flush=True); break
        for r in j['content']: r['_src'] = src; out.write(json.dumps(r) + '\n'); n += 1
        if not j.get('hasNext') or p >= j['totalPages']: break
        p += 1
    print(src, p, n, flush=True)
out.close(); print('DONE', flush=True)
