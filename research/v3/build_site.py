# Build the research report (report/index.html) and the terminal page (site/index.html) from data/report.json.
import json, sys, os, shutil
S = __import__('os').environ.get('CT_WORK', './work')
url = sys.argv[1] if len(sys.argv) > 1 else ''
val = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
R = json.load(open(f'{S}/data/report.json')); X = json.load(open(f'{S}/data/short_events.json'))
R['curves'].pop('BSE 500', None); R['curve_stats'].pop('BSE 500', None); R['short'] = X; R['validation'] = val
open(f'{S}/report/data.json', 'w').write(json.dumps(R))
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'report.src.html')).read().replace('__DATA__', json.dumps(R, separators=(',', ':')))
open(f'{S}/report/index.html', 'w').write(src)
# page evidence (compact)
L = R['league']; f = lambda s: next(r for r in L if r['name'].startswith(s))
keep = ['Composite top 10% (growth', 'Relative strength', 'Trend template', "CAN SLIM", 'Episodic', 'PEAD', 'GARP', 'Cheap', 'All tradeable']
short = {'Composite top 10% (growth': 'Model pool: composite top 10%', 'Relative strength': 'Relative strength, top 10% (Jegadeesh-Titman)',
         'Trend template': 'Trend template + earnings (Minervini)', 'CAN SLIM': "CAN SLIM core (O'Neil)", 'Episodic': 'Biggest result-day reaction',
         'PEAD': 'Biggest earnings surprise (Bernard-Thomas)', 'GARP': 'PEG below 1 (Lynch GARP)', 'Cheap': 'Cheapest 20% by P/E', 'All tradeable': 'Any result, random picks'}
lg = [dict(name=short[k], cagr=f(k)['cagr'], dd=f(k)['dd'], yearly=f(k)['yearly'], model=k.startswith('Composite')) for k in keep]
cs = R['curve_stats']
bench = [dict(name=n, cagr=cs[k]['cagr'], dd=cs[k]['dd'], yearly={y: cs[k]['yearly'].get(y) for y in ['2023', '2024', '2025', '2026']})
         for n, k in [('Equal-weight liquid universe', 'Equal-weight universe'), ('Nifty Smallcap 250', 'Nifty Smallcap 250'), ('Nifty 50', 'Nifty 50')]]
m = f('Composite top 10% (growth'); b = f('All tradeable'); gc = f('Management cut')
G = {g['name']: g for g in R['gauge']}; g0 = G['no gauge | random order']; g1 = G['scale by gauge (0..1) | random order']
E = {e['name']: e for e in R.get('exits', [])}
D = R['deciles']; rk = next(r for r in L if 'ranked' in r['name'] and 'Composite' in r['name'])
p = lambda v: ('+' if v > 0 else '−' if v < 0 else '') + f'{abs(v)*100:.1f}%'
notes = [
  f"The top 10% returned {p(m['cagr'])} a year against {p(b['cagr'])} for random results under identical rules. Every tenth of the score ranks in order: the bottom tenth trailed the market by {p(D[0]['mean'])} over 60 sessions, the top tenth beat it by {p(D[9]['mean'])}.",
  f"Approaches that pair earnings with price leadership win; buying cheapness does not. Valuation screens did no better than random picks.",
  f"A guidance cut on the concall is the clearest warning in the data ({p(gc['cagr'])} a year as a pool), so it is excluded.",
  f"Drift needs time: 20, 40, 60 and 120-session holds gave {p(E['Hold 20 sessions']['cagr'])}, {p(E['Hold 40 sessions']['cagr'])}, {p(E['Hold 60 sessions (model)']['cagr'])} and {p(E['Hold 120 sessions']['cagr'])} a year. Selling below the 50-day average gave {p(E['Exit on close below 50-day average']['cagr'])}." if E else "",
  f"The market gauge is insurance: without it {p(g0['cagr'])} a year but a {p(g0['dd'])} worst fall; with it {p(g1['cagr'])} and {p(g1['dd'])}.",
  f"Inside the top 10% the order barely matters (score-ordered path {p(rk['cagr'])}). Treat each season's buys as a basket.",
]
ev = dict(league=lg, bench=bench, years=['2023', '2024', '2025', '2026'], events=R['census']['events_scored'], **{'from': 'Oct 2022'}, to='Oct 2026', notes=[n for n in notes if n])
page = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../web/') + 'index.src.html').read().replace('__EVIDENCE__', json.dumps(ev, ensure_ascii=False)).replace('__REPORT_URL__', url)
os.makedirs(f'{S}/site', exist_ok=True)
open(f'{S}/site/index.html', 'w').write(page)
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../web/') + '_worker.js', f'{S}/site/_worker.js')
print('built', len(src), len(page))
