# Point-in-time StockScans panels for v4 factor tests. Usage: pull_ss_v4.py TYPE date1,date2,...  (mcap >= 1000 cr)
# Sleeps through the nightly StockScans job window (17:25-20:40 UTC) so the terminal's own pull is never rate-limited by us.
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__))
from api import ss, S
OUT = f'{S}/data/ssp'; CK = f'{OUT}/_ck4.json'; LOG = open(f'{OUT}/_log4.txt', 'a')
def log(*a): LOG.write(time.strftime('%H:%M:%S ') + ' '.join(map(str, a)) + '\n'); LOG.flush()
def quiet():
    while True:
        t = time.gmtime(); m = t.tm_hour * 60 + t.tm_min
        if 17 * 60 + 25 <= m <= 20 * 60 + 40: time.sleep(300); continue
        return
ck = json.load(open(CK)) if os.path.exists(CK) else {}
rt = sys.argv[1]; dates = sys.argv[2].split(',')
scan = {'scanId': '', 'scanName': 'x', 'industry': [], 'index': [], 'tags': [], 'filters': [{'left': 'Market Capitalization', 'sign': '>=', 'right': '1000'}]}
for d in dates:
    key = f'{d}|{rt}'; st = ck.get(key, {'off': 0})
    if st.get('done'): continue
    f = open(f'{OUT}/v4_{rt.replace("/", "_").replace(" ", "_")}.jsonl', 'a')
    while True:
        wait = 60
        while True:
            quiet()
            try:
                c, j = ss('/api/scans/stock/run', {'ratiosType': rt, 'timePeriod': d, 'scan': scan, 'watchlistIds': [], 'order': 'desc', 'orderBy': 'Market Capitalization', 'offset': st['off']}, ref='https://www.stockscans.in/stock-scans')
            except Exception as e:
                c, j = 0, repr(e)
            if c == 200 and isinstance(j, dict) and 'table' in j: break
            if c in (401, 403): log('AUTH FAIL'); sys.exit(1)
            log('HTTP', c, str(j)[:80], 'sleep', wait); time.sleep(wait); wait = min(wait * 2, 600)
        hdr = j['table'][0]
        for r in j['table'][1:]: f.write(json.dumps({'d': d, 'row': dict(zip(hdr, r))}) + '\n')
        f.flush()
        if not j.get('end') or j['end'] >= j.get('total', 0): st['done'] = True
        else: st['off'] = j['end']
        ck[key] = st; json.dump(ck, open(CK, 'w'))
        if st.get('done'): break
        time.sleep(2)
    log('done', key, j.get('total'))
log('ALL DONE', rt)
