# One-off backfill: EquiSense history (jsonl pulled by pull_es_hist.py) -> CT tables via ct-ingest.
import json, glob, hashlib, sys, urllib.request, datetime, time, os
S = os.environ.get('CT_SCRATCH', '/tmp/ct-scratch')
URL = 'https://ybdqdpwfhgngggaomvqq.supabase.co/functions/v1/ct-ingest'
A = open(f'{S}/secrets/ct_anon').read().strip(); K = open(f'{S}/secrets/ingest_key').read().strip()
FULL_Q = {'Q2FY2027', 'Q1FY2027'}          # keep full text for the live + previous season
def post(table, rows, oc):
    for i in range(0, len(rows), 1000):
        body = json.dumps({'table': table, 'rows': rows[i:i+1000], 'on_conflict': oc}).encode()
        for a in range(4):
            try:
                r = urllib.request.urlopen(urllib.request.Request(URL, data=body, method='POST', headers={'Authorization': 'Bearer ' + A, 'x-ct-key': K, 'Content-Type': 'application/json'}), timeout=150)
                j = json.loads(r.read()); assert j.get('ok'), j; break
            except Exception as e:
                print('retry', table, i, e, flush=True); time.sleep(5 * (a + 1))
        else: raise SystemExit('failed ' + table)
def iso(ms): return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).isoformat() if ms else None
DROP_R = ['resultSummaryText', 'insightsJson', 'peadReason', 'resultVerdictReason', 'meteringStatus', 'locked', 'currentPrice', 'priceMovePct']
DROP_C = ['shortSummaryText', 'managementGuidance', 'forwardMetrics', 'managementToneReason', 'guidanceRevisionReason', 'guidanceDeliveryReason',
          'convictionLevelReason', 'analystSentimentReason', 'managementCandorReason', 'earningsQualityReason', 'turnaroundReason', 'storyTypeReason', 'meteringStatus']
def res_row(r, full):
    raw = dict(r) if full else {k: v for k, v in r.items() if k not in DROP_R}
    for k in ('ecsScore', 'marketCap', 'pe', 'currentPrice', 'priceMovePct'): raw.pop(k, None) if not full else None
    return dict(id=r['id'], isin=r.get('isin'), symbol=r.get('symbol'), q=r.get('quarter'), fy=r.get('fy'), announced_at=iso(r.get('resultAnnouncementEpoch')),
                ecs=r.get('ecsScore') if full else None, verdict=r.get('resultVerdict'), pead_label=r.get('peadLabel'), pead_index=r.get('peadIndex'),
                bsh=r.get('balanceSheetHealth'), raw=raw)
def cc_row(r, full):
    raw = dict(r) if full else {k: v for k, v in r.items() if k not in DROP_C}
    return dict(id=r['id'], isin=r.get('isin'), symbol=r.get('symbol'), q=r.get('quarter'), fy=r.get('year'), concall_at=iso(r.get('concallEventEpoch')),
                guidance_revision=r.get('guidanceRevision'), guidance_delivery=r.get('guidanceDelivery'), tone=r.get('managementTone'), candor=r.get('managementCandor'),
                earnings_quality=r.get('earningsQuality'), analyst_sentiment=r.get('analystSentiment'), story_type=r.get('storyType'), raw=raw)
def smart_id(r):
    return hashlib.md5('|'.join(str(r.get(k)) for k in ('source', 'dealDate', 'isin', 'dealType', 'netQuantity', 'topCounterparty', 'personCategory', 'mode')).encode()).hexdigest()
def smart_row(r):
    return dict(id=smart_id(r), source=r.get('source'), deal_date=r.get('dealDate'), isin=r.get('isin'), symbol=r.get('symbol'), side=r.get('dealType'),
                net_value=r.get('netValueRupees'), raw=r)
def filing_row(r, kind):
    return dict(id=r['id'], kind=kind, isin=r.get('isin'), symbol=r.get('symbol'), filed_at=iso(r.get('filedAt')), impact=r.get('impactScore'),
                direction=r.get('impactDirection'), raw=r)
if __name__ == '__main__':
    what = sys.argv[1:] or ['results', 'concalls', 'smart', 'filings']
    if 'results' in what:
        for f in sorted(glob.glob(f'{S}/data/es/results_Q*.jsonl')):
            q = f.split('results_')[1][:-6]; rows = {}
            for l in open(f): r = json.loads(l); rows[r['id']] = res_row(r, q in FULL_Q)
            post('ct_es_results', list(rows.values()), 'id'); print('results', q, len(rows), flush=True)
    if 'concalls' in what:
        for f in sorted(glob.glob(f'{S}/data/es/concalls_Q*.jsonl')):
            q = f.split('concalls_')[1][:-6]; rows = {}
            for l in open(f): r = json.loads(l); rows[r['id']] = cc_row(r, q in FULL_Q)
            post('ct_es_concalls', list(rows.values()), 'id'); print('concalls', q, len(rows), flush=True)
    if 'smart' in what:
        rows = {}
        for f in glob.glob(f'{S}/data/es/smart_*.jsonl'):
            for l in open(f): r = smart_row(json.loads(l)); rows[r['id']] = r
        post('ct_es_smart', list(rows.values()), 'id'); print('smart', len(rows), flush=True)
    if 'filings' in what:
        rows = {}
        for f in glob.glob(f'{S}/data/es/filings_*.jsonl'):
            kind = f.split('filings_')[1][:-6]
            for l in open(f): r = filing_row(json.loads(l), kind); rows[r['id']] = r
        post('ct_es_filings', list(rows.values()), 'id'); print('filings', len(rows), flush=True)
