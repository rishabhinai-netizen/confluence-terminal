# Build the v4 terminal page (site/index.html) with its static evidence block.
import json, sys, os, shutil, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import rs2
S = rs2.S; REPO = os.environ.get('CT_REPO', '/home/claude/confluence-terminal')
url = sys.argv[1] if len(sys.argv) > 1 else ''
BF = pd.read_pickle(f'{S}/data/books_final.pkl'); r = BF['r']; st = BF['stats']
def cs(x, start, end=None):
    x = x.loc[start:end]; eq = (1 + x).cumprod(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    y = eq.resample('YE').last(); pv = np.r_[1.0, y.values[:-1]]
    return float(eq.iloc[-1] ** (1 / yrs) - 1), float((eq / eq.cummax() - 1).min()), {str(k.year): float(a / b - 1) for k, a, b in zip(y.index, y.values, pv)}
years = [str(y) for y in range(2019, 2027)]
rows = []
for k, nm in [('Trend', 'Trend: 55-day breakout, stop at 50-day average'), ('Swing', 'Swing: 10-day breakout, exit below 10-day EMA'), ('Results', 'Results Leaders: top 10% of the season, 60 sessions (15 slots)')]:
    a = cs(r[k], '2018-07-01'); b = cs(r[k], '2023-01-01')
    rows.append(dict(name=nm, all=a[0] if k != 'Results' else None, dd=a[1] if k != 'Results' else None, s23=b[0], dd23=b[1], yearly={y: (a[2].get(y) if (k != 'Results' or y >= '2023') else None) for y in years}))
eqt = (r['Trend'] + r['Swing'] + r['Results']) / 3; b = cs(eqt, '2023-01-01')
rows.append(dict(name='All three, equal thirds', s23=b[0], dd23=b[1], all=None, dd=None, yearly={y: b[2].get(y) for y in years}, hl=True))
P = rs2.panel(); m = P['mret'].loc['2018-07-01':]
a = cs(m, '2018-07-01'); b = cs(m, '2023-01-01')
rows.append(dict(name='Equal-weight market (benchmark)', all=a[0], dd=a[1], s23=b[0], dd23=b[1], yearly={y: a[2].get(y) for y in years}))
REP = json.load(open(f'{S}/data/report.json'))['curve_stats']
for nm in ['Nifty Smallcap 250', 'Nifty 50']:
    x = REP[nm]; rows.append(dict(name=nm + ' (benchmark)', all=None, dd=None, s23=x['cagr'], dd23=x['dd'], yearly={y: x['yearly'].get(y) for y in years}))
ev = dict(
  lede='Every classic approach the data could support was run through the same machine: daily prices for about 1,900 stocks since 2018 (covering the 2020 crash and the 2022 bear market), results and concalls since 2022, and StockScans point-in-time panels since 2025. Rules were fixed on 2018–22 and checked on 2023–26. Exits are executable: no rule assumes you can trade at a close you have not yet seen.',
  years=years, books=rows,
  worked=['Price leadership: breakouts to new highs, bought strongest-first by 6-month relative strength (Turtle/Donchian, Darvas, Minervini, O\'Neil all point here). Breakout lengths of 40–100 days all gave 29–34% a year.',
          'Buying stocks that have already run: the more extended the breakout, the better the trade. "Missed it" is not a reason to skip.',
          'The latest result rank (growth ×2, trend, reaction) as a season strategy, and as a factor (60-day IC 0.08).',
          'The 3-vote market gauge: it halves the worst fall of the Trend book (−39% to −19%).',
          'Running three books together: worst fall −17% since 2023, against −19% to −24% for each book alone.'],
  failed=['Mean reversion after costs: Connors RSI-2, 3-day drops, weekly losers (−3% to −8% a year).',
          'Pullbacks to the 20- or 50-day average in leaders, and the 4% momentum burst (negative after costs).',
          'Valuation (low P/E, PEG), FII/DII/promoter holding changes, ROE/ROCE/margins: no edge on top of price.',
          'Volume surge on the breakout day, guidance or results filters inside the Trend book: no improvement.',
          'Smart-money deals and concall tone fields: about a year of history only. Kept as watch flags, not rules.'])
page = open(f'{REPO}/web/index.src.html').read().replace('__EVIDENCE__', json.dumps(ev, ensure_ascii=False)).replace('__REPORT_URL__', url)
os.makedirs(f'{S}/site', exist_ok=True); open(f'{S}/site/index.html', 'w').write(page)
shutil.copy(f'{REPO}/web/_worker.js', f'{S}/site/_worker.js')
json.dump(ev, open(f'{S}/data/evidence_v4.json', 'w'), indent=1)
print('built', len(page)); [print(f"{x['name'][:40]:40s}", x['all'], x['s23']) for x in rows]
