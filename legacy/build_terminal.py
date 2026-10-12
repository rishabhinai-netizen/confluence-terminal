"""
Confluence Terminal v3 — Build script
=====================================
Reads all 5 source Excels (EquiSense Results/Concalls/Merged, StockScans Concalls,
StockScans 26 pre-built scans, StockScans Market Scans + Score History) and emits
a self-contained HTML terminal at ./Confluence Terminal v3.html.

Enrichments added in v3 over v2:
  1. Signal Stack — cross-references every stock against 26 StockScans screens
  2. Momentum trajectory + slope (from 25-day Score History averaged across
     each stock's index/industry buckets)
  3. Result Date + Concall Date surfaced everywhere
  4. Rebuilt conviction formula: collapses SS/ES sentiment correlation,
     adds confluence multiplier, adds signal-stack + freshness components
  5. Expandable intelligence card per pick with Verdict Reason, top
     POSITIVE/NEGATIVE insights, verbatim guidance, forward metrics,
     StockScans highlights, PDF & audio links
  6. Symmetric Avoid Board (Red Flags)
  7. Sector rotation inflection screen
  8. Coverage transparency strip
  9. Per-stock deep-dive route via URL hash
 10. Portfolio-level sector concentration for current shortlist

Run:
    python build_terminal.py --data-dir "path/to/Confluence" --out "Confluence Terminal v3.html"
Default data-dir is the current directory.
"""
from __future__ import annotations
import argparse, json, math, re, html, os, sys, datetime as dt
from pathlib import Path
from collections import defaultdict, Counter, OrderedDict

import pandas as pd
import numpy as np


# ---------- SNAPSHOT / TREND TRACKING ----------
def load_prior_snapshot(snapshot_dir: Path):
    """Load the most recent prior snapshot for trend comparison."""
    if not snapshot_dir.exists(): return None, None
    snaps = sorted(snapshot_dir.glob('*.json'))
    if not snaps: return None, None
    prior_path = snaps[-1]
    return json.loads(prior_path.read_text()), prior_path.stem  # returns (dict, date_string)


def save_snapshot(snapshot_dir: Path, payload: dict, date_str: str):
    """Persist today's rankings for tomorrow's trend delta calculation."""
    snapshot_dir.mkdir(exist_ok=True, parents=True)
    snap = {
        'built_at': date_str,
        'top_picks': payload['top_picks'],
        'fast_growers': payload['fast_growers'],
        'avoid': payload['avoid'],
        'soic_picks': payload['soic_picks'],
        'conviction_by_ticker': {c['ticker']: c['conviction']
                                  for c in payload['companies'] if c.get('conviction')},
    }
    out_path = snapshot_dir / f'{date_str}.json'
    out_path.write_text(json.dumps(snap))
    # Keep only last 60 snapshots
    all_snaps = sorted(snapshot_dir.glob('*.json'))
    for old in all_snaps[:-60]:
        old.unlink()


def compute_deltas(current: list, prior: dict | None, list_key: str):
    """Compute rank movement per ticker.
    Returns {ticker: {'prev_rank': N or None, 'delta': int or None, 'status': str}}"""
    out = {}
    prior_list = (prior or {}).get(list_key, []) if prior else []
    prior_rank = {t: i+1 for i, t in enumerate(prior_list)}
    for i, t in enumerate(current, 1):
        prev = prior_rank.get(t)
        if prev is None:
            out[t] = {'prev_rank': None, 'delta': None, 'status': 'NEW'}
        else:
            d = prev - i  # positive = moved UP
            out[t] = {'prev_rank': prev, 'delta': d,
                      'status': 'UP' if d > 0 else 'DOWN' if d < 0 else 'SAME'}
    # Dropouts — in prior but not in current
    dropouts = [t for t in prior_list if t not in set(current)]
    return out, dropouts


def compute_conviction_delta(companies: list, prior: dict | None):
    """Per-stock conviction change vs prior build."""
    prior_conv = (prior or {}).get('conviction_by_ticker', {}) if prior else {}
    for c in companies:
        pc = prior_conv.get(c['ticker'])
        if pc is not None and c.get('conviction') is not None:
            c['conviction_prev'] = pc
            c['conviction_delta'] = round(c['conviction'] - pc, 1)
        else:
            c['conviction_prev'] = None
            c['conviction_delta'] = None


def entry_reason(c: dict) -> str:
    """One-line reason why a stock qualifies for Top Picks now."""
    bits = []
    if c.get('es_verdict') == 'BEAT': bits.append('BEAT verdict')
    if c.get('es_ai_tag') == 'Fantastic': bits.append('AI-2 tag Fantastic')
    elif c.get('es_ai_tag') == 'Good': bits.append('AI-2 tag Good')
    if c.get('es_bsh') == 'STRONG': bits.append('STRONG balance sheet')
    if c.get('sig_count', 0) >= 5: bits.append(f'{c["sig_count"]}-signal stack')
    if (c.get('pat_yoy') or 0) > 50: bits.append(f'PAT YoY +{c["pat_yoy"]:.0f}%')
    if c.get('es_guidance_move') == 'RAISED': bits.append('Guidance raised')
    if (c.get('momentum') or 0) >= 75: bits.append(f'Momentum {c["momentum"]:.0f}')
    return ' · '.join(bits[:4]) or 'Broad-based confluence'


def drop_reason(c: dict, prior_conv: dict | None) -> str:
    """One-line reason a previously-listed stock dropped out."""
    bits = []
    if c.get('es_verdict') == 'MISS': bits.append('Verdict flipped to MISS')
    elif not c.get('es_verdict'): bits.append('No fresh verdict')
    if c.get('es_bsh') in ('WEAK', 'STRESSED'): bits.append(f'BSH weakened to {c["es_bsh"]}')
    if c.get('es_guidance_move') == 'CUT': bits.append('Guidance CUT')
    if (c.get('momentum') or 100) < 40: bits.append(f'Momentum collapsed to {c["momentum"]:.0f}')
    if c.get('es_ai_tag') == 'Weak': bits.append('AI-2 tag downgraded to Weak')
    # Conviction drift check (more sensitive threshold)
    if prior_conv and c.get('ticker') in prior_conv:
        old = prior_conv[c['ticker']]
        new = c.get('conviction')
        if new is not None and old is not None:
            drift = old - new
            if drift >= 3:
                bits.append(f'Conviction slipped {old:.1f} → {new:.1f}')
            elif drift >= 0.5 and not bits:
                # Small drift + no other flags = pushed out by rising picks
                bits.append(f'Conviction dipped ({old:.1f} → {new:.1f}); still qualifies but pushed out of top 30 by rising entrants')
            elif drift <= 0 and not bits:
                bits.append(f'Conviction essentially flat ({old:.1f} → {new:.1f}); displaced by other stocks moving up faster')
    return ' · '.join(bits[:3]) or 'Displaced by higher-conviction entrants — still qualifies as a candidate, just outside the top 30'


# ---------- CONFIG ----------
SIGNAL_WEIGHTS = {
    # Ownership / smart-money signals — highest weight (independent from AI sentiment)
    'Insider Trading Buying': 3.0,
    'Smart Money Moves': 2.5,
    'Institutional Influx': 2.0,
    'Bulk Block Deals': 1.2,
    # Fundamental screens
    'Driving Deleverage': 2.0,
    'Margin Mavericks': 2.0,
    'Buoyant Growth': 1.5,
    'Explosive Growth': 1.8,
    # Technical momentum / breakout screens
    'Alpha Leaders': 1.8,
    'Techno Funda': 1.6,
    'Long Term Breakout': 1.4,
    'Short Term Breakout': 1.0,
    'Breakout Horizon': 1.0,
    'Turbo Surge': 1.2,
    'Cyclone': 1.0,
    'The Consolidators': 1.0,
    'Movers Shakers': 0.7,
    'Volume Rocketing': 0.8,
    'Weekly Trend Twist': 0.7,
    'Monthly Trend Twist': 0.7,
    'Early Stage2': 0.9,
    'Index Outperformance 3 Months': 1.1,
    'Index Outperformance 1 Year': 0.9,
    'Industry Outperformance 3 Month': 1.1,
    # Negative signals — subtracted
    'Insider Trading Selling': -2.5,
    'Bombed Out Ipo': -1.5,
}

# ---- SOIC × StockScans "Fastest Growing Businesses" Q1FY27 curated universe ----
# Sourced from the report's table of contents (SOIC/Stockscans, dated 15 Aug 2026).
# Themes cut across NSE sector classifications — e.g., "Data Centre Proxies" pools
# telecom (HFCL, STLTECH), power (TDPOWERSYS), industrial (MTAR, AEROFLEX),
# and IT (E2E) into one investable narrative.
SOIC_UNIVERSE = {
    'Auto Ancillaries': ['TVSMOTOR', 'ATHERENERG', 'LUMAXTECH', 'ASKAUTOLTD',
                         'PRICOLLTD', 'SJS', 'SSWL', 'DIVGIITTS'],
    'CDMO & Healthcare': ['DIVISLAB', 'LAURUSLABS', 'GLAND', 'EMCURE', 'NEULANDLAB',
                          'ACUTAAS', 'ONESOURCE', 'SHILPAMED', 'CONCORDBIO',
                          'AARTIPHARM', 'INNOVACAP', 'MOREPENLAB'],
    'Chemicals': ['NAVINFLUOR', 'AETHER', 'DEEPAKFERT', 'NEOGEN', 'YASHO', 'ELLEN'],
    'Consumption': ['RADICO', 'HONASA', 'TI', 'SAREGAMA', 'BECTORFOOD',
                    'HNDFDS', 'STYLAMIND', 'TCPLPACK'],
    'Data Centre Proxies': ['HFCL', 'STLTECH', 'TDPOWERSYS', 'MTARTECH',
                            'E2E', 'AEROFLEX'],
    'Engineered Goods / EMS': ['SYRMA', 'TECHNOE', 'CYIENTDLM', 'RRWL', 'MACPOWER'],
    'Financial Services': ['BSE', 'BILLIONBRAIN', 'GROWW', 'MCX', '360ONE'],
    'Forging & Castings': ['SONACOMS', 'HAPPYFORGE', 'RKFORGE', 'STEELCAS', 'MMFL'],
    'Hospitals & Diagnostics': ['APOLLOHOSP', 'VIJAYA', 'PARKMEDI', 'HCG',
                                'THYROCARE', 'ARTEMISMED'],
    'Internet / Platform / IT': ['PAYTM', 'COFORGE', 'TATATECH', 'PHYSICSWAL',
                                 'SHADOWFAX', 'CARTRADE', 'RATEGAIN'],
    'Jewellery': ['TITAN', 'KALYANKJIL', 'SKYGOLD', 'GOLDIAM', 'PNGSREVA'],
    'Metals': ['HINDZINC', 'LLOYDSME', 'USHAMART', 'JAYNECOIND', 'IMFA'],
    'Niche Businesses': ['GRWRHITECH', 'PRIVISCL', 'MANORAMA'],
    'Power & Ancillaries': ['POWERINDIA', 'APARINDS', 'KEI', 'RRKABEL',
                            'ATLANTAELE', 'QPOWER', 'KSHINTL', 'UNIVCABLES'],
    'Precision Engineering': ['MSUMI', 'SANSERA', 'AZAD', 'DYNAMATECH',
                              'OMNITECH', 'SHIVALIK', 'KDDL', 'NRBBEARING', 'UNIPARTS'],
    'Tubes / Pipes': ['WELCORP', 'DEEDEV', 'SAMBHV'],
}
SOIC_THEME_OF_TICKER = {t: theme for theme, tickers in SOIC_UNIVERSE.items() for t in tickers}
SOIC_ALL_TICKERS = set(SOIC_THEME_OF_TICKER.keys())

# ---- 6-quarter median YoY growth history — transcribed from SOIC×StockScans PDF
# pages 6-12 (Q1FY27 report, 15 Aug 2026). Each row: [Rev%, OpProfit%, PAT%].
# Quarters run oldest → newest: Mar 25, Jun 25, Sep 25, Dec 25, Mar 26, Jun 26.
SOIC_HISTORY_QUARTERS = ['Mar 25', 'Jun 25', 'Sep 25', 'Dec 25', 'Mar 26', 'Jun 26']
SOIC_MARKET_HISTORY = {
    'Nifty 50':       [[9.4, 9.5, 12.7], [9.5, 4.2, 9.9], [9.9, 13.3, 9.9], [10.9, 8.8, 5.2], [12.3, 15.3, 10.0], [16.4, 19.2, 18.5]],
    'Nifty 500':      [[11.0, 14.3, 17.9], [10.1, 10.5, 13.0], [10.7, 15.7, 14.1], [12.7, 16.1, 11.0], [13.5, 17.0, 18.3], [17.3, 20.0, 19.3]],
    'Nifty Smallcap 250':[[11.6, 16.0, 20.8], [9.5, 9.3, 15.3], [10.8, 16.9, 15.4], [13.2, 18.7, 10.4], [13.1, 15.4, 16.9], [17.2, 20.5, 18.9]],
    'Nifty Microcap 250':[[10.7, 14.7, 16.9], [9.1, 13.9, 14.8], [13.0, 16.5, 18.3], [12.6, 19.7, 13.1], [15.0, 20.3, 27.2], [19.0, 23.2, 25.3]],
}
SOIC_SECTOR_HISTORY = {
    'Nifty Auto':     [[8.5, 5.0, 1.2], [9.2, 3.2, 19.4], [13.1, 12.6, 18.7], [22.9, 20.8, 16.2], [17.9, 20.4, 15.3], [23.8, 23.6, 2.1]],
    'Nifty Pharma':   [[10.8, 17.3, 25.5], [11.2, 14.1, 8.8], [14.2, 18.6, 18.0], [12.9, 19.1, 11.8], [10.7, 12.5, 15.8], [18.5, 23.6, 25.8]],
    'Nifty Healthcare':[[11.9, 17.3, 24.9], [11.3, 18.2, 13.0], [15.2, 18.6, 20.3], [11.1, 13.9, 5.8], [10.7, 15.7, 7.5], [17.0, 17.3, 16.6]],
    'Nifty Chemicals':[[8.2, 13.6, 34.8], [9.6, 12.0, 20.4], [7.3, 11.2, 19.7], [8.0, 11.4, 5.7], [12.3, 11.9, 12.3], [21.4, 20.7, 28.8]],
    'Nifty FMCG':     [[8.5, 3.3, 15.2], [9.4, -1.1, 3.2], [4.3, 5.9, 3.8], [8.2, 10.2, 24.8], [9.1, 8.2, 20.2], [11.8, 11.0, 14.1]],
    'Nifty IT':       [[7.0, 8.0, 14.3], [7.8, 4.8, 9.5], [9.4, 9.6, 5.9], [12.0, 12.8, 0.5], [13.9, 19.1, 19.8], [17.6, 14.3, 15.4]],
    'Nifty Financial Services':[[13.4, 8.8, 8.8], [12.3, 6.8, 14.5], [10.9, 11.1, 8.0], [13.1, 3.3, 1.8], [5.2, 11.3, 8.8], [13.3, 25.7, 20.7]],
    'Nifty Metal':    [[4.9, 4.2, 51.9], [3.8, 10.5, 18.4], [9.1, 24.3, 40.7], [11.8, 18.6, 46.2], [20.3, 29.4, 46.7], [25.9, 50.0, 77.7]],
}

# Generic display aliases for the pre-built scan names (source-agnostic)
SCAN_ALIAS = {
    'Insider Trading Buying':       'Promoter Buying',
    'Insider Trading Selling':      'Promoter Selling',
    'Smart Money Moves':            'Institutional Bias Shift',
    'Institutional Influx':         'Institutional Inflow',
    'Bulk Block Deals':             'Block Deal Activity',
    'Driving Deleverage':           'Deleveraging',
    'Margin Mavericks':             'Margin Expansion',
    'Buoyant Growth':               'Steady Growth',
    'Explosive Growth':             'Hypergrowth',
    'Alpha Leaders':                'Sector Leaders',
    'Techno Funda':                 'Techno-Fundamental',
    'Long Term Breakout':           'Long-Run Breakout',
    'Short Term Breakout':          'Short-Run Breakout',
    'Breakout Horizon':             'Emerging Breakout',
    'Turbo Surge':                  'Momentum Burst',
    'Cyclone':                      'Cyclical Surge',
    'The Consolidators':            'Consolidation Base',
    'Movers Shakers':               'Big Movers',
    'Volume Rocketing':             'Volume Surge',
    'Weekly Trend Twist':           'Weekly Reversal',
    'Monthly Trend Twist':          'Monthly Reversal',
    'Early Stage2':                 'Early-Stage Setup',
    'Bombed Out Ipo':               'Distressed IPO',
    'Index Outperformance 3 Months':'3-Month Index Outperformance',
    'Index Outperformance 1 Year':  '1-Year Index Outperformance',
    'Industry Outperformance 3 Month':'3-Month Industry Outperformance',
    'Result Calendar':              'Result Calendar',
    'Post Earnings Announcement Drift':'Post-Earnings Drift',
    'Quarterly Growth Picks':       'Quarterly Growth',
}

# Scans grouped for badge display
SCAN_GROUPS = {
    'Ownership': ['Insider Trading Buying', 'Smart Money Moves', 'Institutional Influx', 'Bulk Block Deals'],
    'Fundamentals': ['Driving Deleverage', 'Margin Mavericks', 'Buoyant Growth', 'Explosive Growth'],
    'Momentum': ['Alpha Leaders', 'Techno Funda', 'Long Term Breakout', 'Short Term Breakout',
                 'Breakout Horizon', 'Turbo Surge', 'Cyclone', 'The Consolidators',
                 'Movers Shakers', 'Volume Rocketing', 'Weekly Trend Twist', 'Monthly Trend Twist',
                 'Early Stage2', 'Index Outperformance 3 Months', 'Index Outperformance 1 Year',
                 'Industry Outperformance 3 Month'],
    'Warning': ['Insider Trading Selling', 'Bombed Out Ipo'],
}
GROUP_OF_SCAN = {s: g for g, ss in SCAN_GROUPS.items() for s in ss}


# ---------- HELPERS ----------
def strip_pfx(s):
    if isinstance(s, str) and ':' in s:
        return s.split(':', 1)[1].strip()
    return s

def safe_num(x, default=None):
    if x is None: return default
    try:
        f = float(x)
        if math.isnan(f) or math.isinf(f): return default
        return f
    except (ValueError, TypeError):
        return default

def clamp(x, lo, hi):
    if x is None: return None
    return max(lo, min(hi, x))

def norm_pct_to_100(pct, cap_at=100):
    """Normalize a percentage growth number to 0-100 with soft cap."""
    if pct is None: return 50
    v = safe_num(pct)
    if v is None: return 50
    if v >= cap_at: return 100
    if v <= -cap_at: return 0
    return 50 + (v / cap_at) * 50

def bsh_to_score(bsh):
    return {'STRONG': 90, 'STABLE': 70, 'WEAK': 40, 'STRESSED': 20}.get(bsh, 50)

def verdict_to_score(v):
    return {'BEAT': 85, 'IN_LINE': 55, 'MISS': 25}.get(v, 50)

def sentiment_to_score(s):
    if not s: return 50
    s = str(s).strip()
    return {'Bullish': 85, 'Neutral': 50, 'Bearish': 20, 'Fantastic': 92,
            'Good': 72, 'Weak': 30}.get(s, 50)

def guidance_to_score(g):
    return {'RAISED': 90, 'MAINTAINED': 70, 'CONSERVATIVE': 45,
            'CUT': 25, 'MISS': 15, 'NONE': 55, 'NO_GUIDANCE': 50}.get(g, 55)

def fmt_date(x):
    if x is None: return ''
    if isinstance(x, str): return x[:10]
    try:
        return pd.to_datetime(x).strftime('%d %b %Y')
    except Exception:
        return str(x)[:10]

def fmt_short_date(x):
    if x is None: return ''
    try:
        return pd.to_datetime(x).strftime('%d %b')
    except Exception:
        return str(x)[:10]


# ---------- INSIGHT PARSING ----------
INSIGHT_RE = re.compile(r'\[(POSITIVE|NEGATIVE|NEUTRAL)\](.*?)(?=\[(?:POSITIVE|NEGATIVE|NEUTRAL)\]|\Z)', re.DOTALL)
def parse_insights(raw):
    """Split '[POSITIVE] text [NEGATIVE] text ...' into structured list."""
    if not raw or not isinstance(raw, str): return []
    out = []
    for m in INSIGHT_RE.finditer(raw):
        tag = m.group(1)
        txt = m.group(2).strip().rstrip('|').strip()
        if txt:
            out.append({'tag': tag, 'text': txt})
    return out


# ---------- SOIC-STYLE GROWTH CATALYSTS EXTRACTION ----------
# Turn our Key Insights (long AI-tagged paragraphs) into SOIC-format numbered
# "Growth Catalysts": short bold headline followed by the evidence sentence.

# Heuristic keyword extraction for catalyst headlines
CATALYST_KEYWORDS = [
    (r'\bcapacity\s+(?:expansion|addition|ramp|utilisation|utilization|expected)', 'Capacity ramp-up'),
    (r'\border\s+book|order\s+inflow|order\s+intake', 'Order book expansion'),
    (r'\bmargin\s+expansion|OPM\s+expanded|EBITDA\s+margin\s+(?:expanded|rose|grew)', 'Margin expansion'),
    (r'\bmarket\s+share|share\s+gain', 'Market share gain'),
    (r'\bnew\s+(?:plant|facility|factory|unit)', 'New facility go-live'),
    (r'\bexport\s+(?:orders?|revenue|growth)', 'Export growth'),
    (r'\bpremiumi[sz]ation|premium\s+(?:mix|segment)', 'Premiumisation'),
    (r'\bdebt\s+reduction|deleverag|net\s+cash|debt-free', 'Balance sheet cleanup'),
    (r'\bfundraise|QIP|preferential\s+allotment|equity\s+infusion', 'Capital infusion'),
    (r'\bacquisition|acquired|merger', 'Inorganic expansion'),
    (r'\bpartnership|MOU|joint\s+venture|JV\s+with', 'Strategic partnership'),
    (r'\bnew\s+product|product\s+launch|launched', 'New product launch'),
    (r'\bpricing\s+power|price\s+(?:hike|increase|realisation|realization)', 'Pricing power'),
    (r'\bR&D|research\s+and\s+development', 'R&D pipeline'),
    (r'\bEV\s+(?:sales|penetration|revenue)|electric\s+vehicle', 'EV ramp'),
    (r'\bAI\s+data\s+cent[er]{2}|data\s+cent[er]{2}\s+(?:revenue|order|deal)', 'Data centre tailwind'),
    (r'\bhyperscal[er]', 'Hyperscaler deal'),
    (r'\bcapex\s+(?:plan|announce|₹)', 'Capex plan'),
    (r'\bguidance\s+(?:raised|upped|revised\s+upward)', 'Guidance raised'),
    (r'\bcross[- ]sell|distribution\s+(?:expansion|scale)', 'Distribution scale-up'),
    (r'\bgross\s+margin|GM\s+expansion', 'Gross margin lift'),
    (r'\btariff\s+(?:hike|increase)|price\s+realisation', 'Tariff-led growth'),
    (r'\bNPA|asset\s+quality|slippage', 'Asset quality trend'),
    (r'\bROE|ROCE|return\s+on\s+(?:equity|capital)', 'Return metrics'),
    (r'\bworking\s+capital|receivables|inventory', 'Working capital'),
    (r'\bsegment\s+revenue|business\s+segment', 'Segment mix shift'),
]

def _catalyst_headline(text: str) -> str:
    """Pattern-match a short 2-4 word headline that captures the catalyst theme."""
    for pat, label in CATALYST_KEYWORDS:
        if re.search(pat, text, re.I):
            return label
    # Fallback: try to grab the first noun phrase (very rough)
    m = re.match(r'([A-Z][a-zA-Z]+(?:\s+[a-z][a-zA-Z]+){1,3})', text.strip())
    if m: return m.group(1)[:40]
    return 'Growth driver'


def _first_sentence(text: str, max_len: int = 260) -> str:
    """Return first 1-2 sentences of text, capped to max_len."""
    if not text: return ''
    s = text.strip()
    # Split on sentence boundary
    m = re.match(r'(.{40,}?[\.!?])\s', s + ' ')
    first = m.group(1) if m else s[:max_len]
    if len(first) < max_len - 60:
        # Add second sentence if room
        rest = s[len(first):].strip()
        m2 = re.match(r'(.{20,}?[\.!?])\s', rest + ' ')
        if m2 and len(first) + len(m2.group(1)) < max_len:
            first = first + ' ' + m2.group(1)
    if len(first) > max_len:
        first = first[:max_len].rstrip() + '…'
    return first.strip()


def build_growth_catalysts(company: dict) -> list:
    """Turn Key Insights (POSITIVE + NEUTRAL) + segment growth mentions +
    Management Guidance into a SOIC-style numbered catalyst list.

    Prioritises POSITIVE tagged insights, dedupes by headline, caps at 6 items.
    Each item: {'headline': short label, 'body': evidence sentence, 'tag': POS/NEU}
    """
    catalysts = []
    seen_headlines = set()

    # Pass 1: POSITIVE insights become primary catalysts
    for ins in company.get('es_key_insights', []):
        if ins['tag'] not in ('POSITIVE', 'NEUTRAL'): continue
        headline = _catalyst_headline(ins['text'])
        if headline in seen_headlines: continue
        seen_headlines.add(headline)
        catalysts.append({
            'headline': headline,
            'body': _first_sentence(ins['text']),
            'tag': ins['tag'],
        })

    # Pass 2: Management guidance sentences become catalysts if we have room
    guid = company.get('es_mgmt_guidance', '')
    if guid and len(catalysts) < 5:
        # Split into sentences
        sents = re.split(r'(?<=[\.!?])\s+', guid)
        for s in sents:
            s = s.strip()
            if len(s) < 30: continue
            headline = _catalyst_headline(s)
            # Prefer guidance-flavoured headlines
            if 'guidance' in s.lower() or 'target' in s.lower() or 'expect' in s.lower():
                if headline not in seen_headlines:
                    seen_headlines.add(headline)
                    catalysts.append({
                        'headline': headline,
                        'body': _first_sentence(s, 220),
                        'tag': 'GUIDANCE',
                    })
                    if len(catalysts) >= 6: break

    return catalysts[:6]


# ---------- SOIC-STYLE COMMITMENT / SPECIFICS / TIMELINE TABLE ----------
# Parse Management Guidance narrative into a 3-column structured table matching
# SOIC's format. Detects commitment nouns, specific numeric targets, and timeline
# phrases (Q2 FY27, by end-FY28, next quarter, etc.).

TIMELINE_RE = re.compile(
    r'\b('
    r'(?:Q[1-4]\s*(?:FY)?(?:20)?\d{2})|'          # Q2 FY27, Q3FY2027
    r'(?:FY(?:20)?\d{2}(?:E)?)|'                    # FY27, FY2027, FY28E
    r'(?:by\s+(?:end[- ])?FY(?:20)?\d{2})|'         # by end-FY27
    r'(?:next\s+(?:quarter|year|(?:few\s+)?quarters))|'
    r'(?:this\s+(?:quarter|year|fiscal))|'
    r'(?:coming\s+quarters?)|'
    r'(?:H[12]\s*FY(?:20)?\d{2})|'                  # H2 FY27
    r'(?:calendar[- ]?(?:20)?\d{2})|'
    r'(?:by\s+\d{4})|'
    r'(?:end[- ]FY(?:20)?\d{2})|'
    r'(?:over\s+the\s+next\s+\d+\s+years?)|'
    r'(?:in\s+\d+[-–]\d+\s+years?)'
    r')\b', re.I)

NUMBER_RE = re.compile(
    r'('
    r'\d+(?:\.\d+)?\s*(?:%|bps|bps\.|basis\s+points|percent|pct)|'
    r'₹\s*\d[\d,\.]*\s*(?:crore|cr\.?|Cr|lakh|lakhs|Lakh|billion|bn)?|'
    r'US?\$\s*\d[\d,\.]*\s*(?:mn|million|bn|billion)?|'
    r'\$\s*\d[\d,\.]*\s*(?:mn|million|bn|billion|M|B)?|'
    r'\d+(?:\.\d+)?x|'                              # 1.2x, 5x
    r'\d+[-–]\d+\s*(?:%|bps|crore|cr)|'
    r'\d{2,}\s*(?:units|MW|GW|MT|tonnes)|'
    r'\d+(?:\.\d+)?\s+(?:crore|cr)\s+(?:units|kg|tonnes)'
    r')', re.I)

COMMITMENT_VERBS = re.compile(
    r'\b(?:target|targeting|expects?|expecting|guiding|guided|guidance|plan(?:ned|s|ning)?|'
    r'aims?|projects?|projected|will\s+(?:reach|scale|grow|expand|hit|touch|achieve|deliver|be)|'
    r'reach|hit|scale\s+to|deliver|achieve|maintain(?:ed)?|revise[ds]?|'
    r'expand(?:ed|s|ing)?\s+to|ramp\s+to|move\s+from|move\s+to)\b', re.I)


SUBJECT_MAP = [
    (r'\bEBITDA\s+margin', 'EBITDA margin'),
    (r'\bgross\s+margin', 'Gross margin'),
    (r'\bOPM', 'OPM'),
    (r'\bcapex', 'Capex'),
    (r'\bcapacity', 'Capacity'),
    (r'\brevenue', 'Revenue guidance'),
    (r'\bPAT|net\s+profit', 'PAT'),
    (r'\border\s+book|order\s+inflow', 'Order book'),
    (r'\bmarket\s+share', 'Market share'),
    (r'\bdata\s+cent[er]{2}', 'Data centre revenue mix'),
    (r'\bexport', 'Exports'),
    (r'\bdebt|deleverag|net\s+cash', 'Debt reduction'),
    (r'\bNIM', 'NIM'),
    (r'\bROE|ROCE|ROA', 'Return metric'),
    (r'\battach\s+rate', 'Attach rate'),
    (r'\bEV\s+', 'EV segment'),
    (r'\bproduct\s+launch|new\s+product', 'Product launch'),
    (r'\bstore\s+(?:count|expansion)', 'Store expansion'),
    (r'\bAUM|assets\s+under\s+management', 'AUM'),
    (r'\bloan\s+book|advances', 'Loan book'),
    (r'\basset\s+quality|NPA|slippage', 'Asset quality'),
]

def _commitment_subject(sent: str, max_len: int = 45) -> str:
    """Extract the subject of the commitment — what's being committed."""
    # Prefer named subject from the SUBJECT_MAP for cleaner labels
    for pat, label in SUBJECT_MAP:
        if re.search(pat, sent, re.I):
            return label
    # Fallback: text before the commitment verb, stripped of filler
    parts = COMMITMENT_VERBS.split(sent, maxsplit=1)
    if len(parts) >= 2 and parts[0].strip():
        subj = parts[0].strip()
    else:
        subj = sent.split(',')[0]
    subj = re.sub(r'^(?:Management|They|We|The\s+company|It|This|A\s+|An\s+|Now|Now\s+)\s*', '', subj, flags=re.I)
    subj = subj.strip(' .,-')
    # If starts with a verb, drop the verb (e.g. "raised FY27..." → "FY27...")
    subj = re.sub(r'^(?:raised|revised|expects?|targeting|planning|has\s+raised|are\s+)\s+', '', subj, flags=re.I)
    subj = subj.strip(' .,-') or 'Commitment'
    if len(subj) > max_len:
        subj = subj[:max_len].rstrip() + '…'
    return subj


def build_commitments(company: dict) -> list:
    """Extract Commitment / Specifics / Timeline rows from Management Guidance.

    Each sentence in Management Guidance is examined for:
      - Commitment verb (target/expect/plan/aim/guide/etc.)
      - Specific number (₹1500 cr, 23%, 5x, ₹700 crore per quarter, ~₹50 crore)
      - Timeline (Q2 FY27, FY28, by end-FY27, next quarter, etc.)
    Only sentences with at least a number OR a timeline become rows.
    """
    guid = company.get('es_mgmt_guidance', '')
    if not guid: return []
    # Add Forward Metrics as pseudo-guidance sentences
    for fm in company.get('es_forward_metrics', []):
        if fm and fm.strip():
            guid = guid + '. ' + fm

    sents = re.split(r'(?<=[\.!?])\s+', guid)
    rows = []
    seen = set()
    for s in sents:
        s = s.strip()
        if len(s) < 25: continue
        numbers = NUMBER_RE.findall(s)
        timelines = TIMELINE_RE.findall(s)
        if not (numbers or timelines):
            continue
        # Extract subject
        subj = _commitment_subject(s)
        specifics = ', '.join(sorted(set(numbers), key=numbers.index)[:3]) if numbers else '—'
        timeline = ', '.join(sorted(set(timelines), key=timelines.index)[:2]) if timelines else '—'
        # Dedupe on subject
        key = subj.lower()[:30]
        if key in seen: continue
        seen.add(key)
        rows.append({
            'commitment': subj,
            'specifics': specifics[:120],
            'timeline': timeline[:60],
        })
        if len(rows) >= 8: break
    return rows


# ---------- LOADERS ----------
def load_sources(data_dir: Path):
    print(f"[load] Reading from {data_dir}")
    es_full = pd.ExcelFile(data_dir / 'EquiSense - Full Dataset (Results + Concalls).xlsx')
    es_res = pd.read_excel(es_full, 'Results (All)')
    es_conc = pd.read_excel(es_full, 'Concalls (All)')
    es_mrg = pd.read_excel(es_full, 'Merged (Results+Concall)')
    ss_conc = pd.read_excel(data_dir / 'Concall Scans - All Data.xlsx')
    ss_mkt_all = pd.ExcelFile(data_dir / 'StockScans - Market Scans (Full).xlsx')
    ss_idx = pd.read_excel(ss_mkt_all, 'Index Summary')
    ss_ind = pd.read_excel(ss_mkt_all, 'Industry Summary')
    ss_const = pd.read_excel(ss_mkt_all, 'All Constituents')
    ss_hist = pd.read_excel(ss_mkt_all, 'Score History (Daily)')
    ss_scans_file = data_dir / 'StockScans - All Scans (26 of 31).xlsx'
    ss_scans_xl = pd.ExcelFile(ss_scans_file)
    scan_sheets = [s for s in ss_scans_xl.sheet_names if s != 'Index']
    ss_scans = {}
    for s in scan_sheets:
        df = pd.read_excel(ss_scans_xl, s)
        if 'companyId' in df.columns:
            df['Ticker'] = df['companyId'].apply(strip_pfx)
            ss_scans[s] = df
    print(f"[load] ES results {len(es_res)}, ES concalls {len(es_conc)}, SS concalls {len(ss_conc)}, "
          f"SS constituents {len(ss_const)}, SS hist {len(ss_hist)}, scans {len(ss_scans)}")
    ss_const['Ticker'] = ss_const['Symbol'].apply(strip_pfx)
    return {
        'es_res': es_res, 'es_conc': es_conc, 'es_mrg': es_mrg,
        'ss_conc': ss_conc, 'ss_idx': ss_idx, 'ss_ind': ss_ind,
        'ss_const': ss_const, 'ss_hist': ss_hist, 'ss_scans': ss_scans,
    }


# ---------- ENRICHMENT ----------
def build_signal_stack(ss_scans):
    """{ticker: {'scans': [aliased names], 'count': int, 'weighted': float, 'groups': {group:count}}}"""
    stack = defaultdict(lambda: {'scans': [], 'count': 0, 'weighted': 0.0,
                                  'groups': Counter()})
    for scan_name, df in ss_scans.items():
        w = SIGNAL_WEIGHTS.get(scan_name, 0.5)
        grp = GROUP_OF_SCAN.get(scan_name, 'Momentum')
        display_name = SCAN_ALIAS.get(scan_name, scan_name)
        for t in df['Ticker'].dropna().unique():
            t = str(t).strip()
            if not t: continue
            stack[t]['scans'].append(display_name)
            stack[t]['count'] += 1
            stack[t]['weighted'] += w
            stack[t]['groups'][grp] += 1
    return dict(stack)


def build_valuation_enrichment(ss_scans):
    """Pull P/E and D/E from scan sheets that surface them (P/E in 26 sheets,
    D/E in Driving Deleverage / Margin Mavericks / Explosive Growth).
    Also opportunistically pulls ROCE where present."""
    pe, de, roce, ps = {}, {}, {}, {}
    for name, df in ss_scans.items():
        cols = df.columns.tolist()
        pe_col = 'Price To Earnings' if 'Price To Earnings' in cols else None
        ps_col = 'Price To Sales' if 'Price To Sales' in cols else None
        de_col = next((c for c in cols if 'Debt' in c or 'D/E' in c), None)
        roce_col = next((c for c in cols if 'ROCE' in c.upper() or 'Return on Capital' in c), None)
        for _, r in df.iterrows():
            t = strip_pfx(r.get('companyId'))
            if not t: continue
            if pe_col and pd.notna(r.get(pe_col)): pe[t] = float(r[pe_col])
            if de_col and pd.notna(r.get(de_col)): de[t] = float(r[de_col])
            if roce_col and pd.notna(r.get(roce_col)): roce[t] = float(r[roce_col])
            if ps_col and pd.notna(r.get(ps_col)): ps[t] = float(r[ps_col])
    return {'pe': pe, 'de': de, 'roce': roce, 'ps': ps}


def build_company_momentum(ss_const, ss_hist):
    """For each company:
       - momentum LATEST = average of per-bucket 'Score' from All Constituents
         (matches the number the site itself displays; this is what v2 used)
       - trajectory (sparkline) = daily average across the company's buckets
         from Score History (kept for the sparkline visual and 5-day change)
    """
    # Latest per-ticker: avg of the sitewide 'Score' column across all buckets the stock sits in
    latest_by_ticker = ss_const.groupby('Ticker')['Score'].mean().round(1).to_dict()
    change_1m_by_ticker = ss_const.groupby('Ticker')['Score Change (1M)'].mean().round(1).to_dict()

    # Bucket → daily series (for trajectory sparkline only)
    hist_by_bucket = {}
    for (bt, bn), grp in ss_hist.groupby(['Bucket Type', 'Bucket Name']):
        g = grp.sort_values('Date')
        hist_by_bucket[(bt, bn)] = list(zip(g['Date'].astype(str).tolist(), g['Score'].tolist()))

    # Company → list of buckets
    comp_buckets = ss_const.groupby('Ticker')[['Bucket Type', 'Bucket Name']].apply(
        lambda x: list(zip(x['Bucket Type'], x['Bucket Name']))).to_dict()

    out = {}
    for ticker, buckets in comp_buckets.items():
        # Daily trajectory (for sparkline visual)
        date_pts = defaultdict(list)
        for b in buckets:
            for date_, score in hist_by_bucket.get(b, []):
                if score is not None and not math.isnan(score):
                    date_pts[date_].append(score)
        traj = sorted([(d, sum(v)/len(v)) for d, v in date_pts.items()])
        scores = [round(s, 1) for _, s in traj]
        latest = latest_by_ticker.get(ticker)
        out[ticker] = {
            'traj': scores,
            'dates': [d for d, _ in traj],
            'latest': latest,                        # from constituents, matches site
            'change_1m': change_1m_by_ticker.get(ticker),
            'change_5d': round(scores[-1] - scores[-6], 1) if len(scores) >= 6 else None,
            'change_full': round(scores[-1] - scores[0], 1) if len(scores) >= 2 else None,
            'slope': round(float(np.polyfit(np.arange(len(scores)), scores, 1)[0]), 2)
                     if len(scores) >= 3 else 0.0,
        }
    return out


# ---------- COMPANY BUILDER ----------
def build_companies(src, momentum, signal_stack, valuation=None):
    valuation = valuation or {'pe': {}, 'de': {}, 'roce': {}, 'ps': {}}
    es_res = src['es_res']
    es_conc = src['es_conc']
    ss_conc = src['ss_conc']

    # Index es_conc by Symbol for O(1) join
    es_conc_by_sym = {}
    for _, r in es_conc.iterrows():
        sym = str(r.get('Symbol', '')).strip()
        if sym: es_conc_by_sym[sym] = r
    ss_conc_by_sym = {}
    for _, r in ss_conc.iterrows():
        sym = str(r.get('Ticker', '')).strip()
        if sym: ss_conc_by_sym[sym] = r

    companies = []
    for _, r in es_res.iterrows():
        sym = str(r.get('Symbol', '')).strip()
        if not sym: continue
        company = {
            'ticker': sym,
            'company': str(r.get('Company', '')).strip(),
            'sector': str(r.get('Sector', '')).strip() if pd.notna(r.get('Sector')) else '',
            'isin': str(r.get('ISIN', '')).strip() if pd.notna(r.get('ISIN')) else '',
            'mcap': safe_num(r.get('Market Cap (Cr)')),
            'result_date': fmt_date(r.get('Date')),
            # Financials
            'rev_cr': safe_num(r.get('Revenue (Cr)')),
            'rev_yoy': safe_num(r.get('Rev YoY %')),
            'ebitda_cr': safe_num(r.get('EBITDA (Cr)')),
            'ebitda_yoy': safe_num(r.get('EBITDA YoY %')),
            'pat_cr': safe_num(r.get('PAT (Cr)')),
            'pat_yoy': safe_num(r.get('PAT YoY %')),
            'opm': safe_num(r.get('OPM %')),
            'opm_yoy_bps': safe_num(r.get('OPM YoY (bps)')),
            'eps_yoy': safe_num(r.get('EPS YoY %')),
            # ES scoring
            'es_ecs': safe_num(r.get('ECS Score')),
            'es_verdict': (str(r.get('Result Verdict', '')).strip()
                           if pd.notna(r.get('Result Verdict')) else ''),
            'es_verdict_reason': (str(r.get('Verdict Reason', '')).strip()
                                  if pd.notna(r.get('Verdict Reason')) else ''),
            'es_bsh': (str(r.get('Balance Sheet Health', '')).strip()
                       if pd.notna(r.get('Balance Sheet Health')) else ''),
            'es_ai_tag': (str(r.get('AI Tag (PEAD Label)', '')).strip()
                          if pd.notna(r.get('AI Tag (PEAD Label)')) else ''),
            'es_pead': safe_num(r.get('PEAD Index')),
            'es_pead_reason': (str(r.get('PEAD Reason', '')).strip()
                              if pd.notna(r.get('PEAD Reason')) else ''),
            'es_drift_conf': safe_num(r.get('Drift Confidence')),
            'es_price_move': safe_num(r.get('Price Move Since Result %')),
            'es_result_summary': (str(r.get('Result Summary', '')).strip()
                                  if pd.notna(r.get('Result Summary')) else ''),
            'es_key_insights': parse_insights(r.get('Key Insights')),
            'es_pdf_url': (str(r.get('PDF URL', '')).strip()
                           if pd.notna(r.get('PDF URL')) else ''),
        }
        # Merge concall (ES side)
        ec = es_conc_by_sym.get(sym)
        if ec is not None:
            company['concall_date'] = fmt_date(ec.get('Date'))
            company['es_concall_ecs'] = safe_num(ec.get('ECS Score'))
            company['es_guidance_move'] = (str(ec.get('Guidance Move', '')).strip()
                                           if pd.notna(ec.get('Guidance Move')) else '')
            company['es_concall_summary'] = (str(ec.get('Summary', '')).strip()
                                             if pd.notna(ec.get('Summary')) else '')
            company['es_mgmt_guidance'] = (str(ec.get('Management Guidance', '')).strip()
                                           if pd.notna(ec.get('Management Guidance')) else '')
            company['es_tags'] = (str(ec.get('Tags', '')).strip()
                                  if pd.notna(ec.get('Tags')) else '')
            fms = []
            for i in (1, 2, 3):
                v = ec.get(f'Forward Metric {i}')
                if pd.notna(v) and str(v).strip():
                    fms.append(str(v).strip())
            company['es_forward_metrics'] = fms
            company['es_recording'] = (str(ec.get('Recording Link', '')).strip()
                                       if pd.notna(ec.get('Recording Link')) else '')
        else:
            company['concall_date'] = ''
            company['es_concall_ecs'] = None
            company['es_guidance_move'] = ''
            company['es_concall_summary'] = ''
            company['es_mgmt_guidance'] = ''
            company['es_tags'] = ''
            company['es_forward_metrics'] = []
            company['es_recording'] = ''

        # Merge SS concall
        sc = ss_conc_by_sym.get(sym)
        if sc is not None:
            company['ss_quality'] = safe_num(sc.get('Result Quality Score'))
            company['ss_quality_tier'] = (str(sc.get('Result Quality Tier', '')).strip()
                                          if pd.notna(sc.get('Result Quality Tier')) else '')
            company['ss_sentiment'] = (str(sc.get('Mgmt Sentiment', '')).strip()
                                       if pd.notna(sc.get('Mgmt Sentiment')) else '')
            company['ss_concall_date'] = fmt_date(sc.get('Date'))
            highlights = []
            for i in (1, 2, 3):
                v = sc.get(f'Highlight {i}')
                if pd.notna(v) and str(v).strip():
                    highlights.append(str(v).strip())
            company['ss_highlights'] = highlights
        else:
            company['ss_quality'] = None
            company['ss_quality_tier'] = ''
            company['ss_sentiment'] = ''
            company['ss_concall_date'] = ''
            company['ss_highlights'] = []

        # If no ES concall date but SS has one, use SS
        if not company['concall_date'] and company['ss_concall_date']:
            company['concall_date'] = company['ss_concall_date']

        # Momentum
        mom = momentum.get(sym)
        if mom:
            company['momentum'] = mom['latest']
            company['momentum_slope'] = mom['slope']
            company['momentum_change_5d'] = mom['change_5d']
            company['momentum_change_full'] = mom['change_full']
            company['momentum_traj'] = mom['traj']
        else:
            company['momentum'] = None
            company['momentum_slope'] = None
            company['momentum_change_5d'] = None
            company['momentum_change_full'] = None
            company['momentum_traj'] = []

        # Signal Stack
        ss = signal_stack.get(sym)
        if ss:
            company['sig_count'] = ss['count']
            company['sig_scans'] = ss['scans']
            company['sig_weighted'] = round(ss['weighted'], 1)
            company['sig_groups'] = dict(ss['groups'])
        else:
            company['sig_count'] = 0
            company['sig_scans'] = []
            company['sig_weighted'] = 0.0
            company['sig_groups'] = {}

        # Valuation enrichment (from SS scan sheets)
        company['pe'] = valuation['pe'].get(sym)
        company['de'] = valuation['de'].get(sym)
        company['roce'] = valuation['roce'].get(sym)
        company['ps'] = valuation['ps'].get(sym)

        # SOIC filter flag: sales>15%, PAT>20%, mcap>10K Cr, D/E<4 (if known), P/E<35 (if known)
        soic_pass = (
            (company.get('rev_yoy') or 0) > 15 and
            (company.get('pat_yoy') or 0) > 20 and
            (company.get('mcap') or 0) > 10000 and
            (company.get('de') is None or company['de'] < 4) and
            (company.get('pe') is None or company['pe'] < 35)
        )
        company['soic_pass'] = soic_pass
        # Fast-grower tier (SOIC "moonshot" bar): PAT YoY 50-500%, Rev YoY 25-300%
        # Upper bounds cut low-base explosions that aren't real growth; mcap ≥ ₹500 Cr
        # excludes illiquid microcaps that plague single-quarter percentage screens
        pat = company.get('pat_yoy') or 0
        rev = company.get('rev_yoy') or 0
        company['fast_grower'] = (
            50 < pat < 500 and
            25 < rev < 300 and
            (company.get('mcap') or 0) >= 500
        )
        # Segment-growth callouts: extract "X% growth" mentions from Key Insights
        seg_callouts = []
        for i in company.get('es_key_insights', []):
            for m in re.finditer(r'(\w[\w\s\-\&]{2,40}?)\s+(?:revenue\s+)?growth\s+of\s+(\d+(?:\.\d+)?)%', i['text'], re.I):
                seg_callouts.append({'seg': m.group(1).strip()[:40], 'pct': float(m.group(2))})
            for m in re.finditer(r'(\w[\w\s\-\&]{2,40}?)\s+grew\s+(\d+(?:\.\d+)?)%', i['text'], re.I):
                seg_callouts.append({'seg': m.group(1).strip()[:40], 'pct': float(m.group(2))})
        company['segment_growth'] = seg_callouts[:5]

        # SOIC coverage flag
        company['soic_covered'] = sym in SOIC_ALL_TICKERS
        company['soic_theme'] = SOIC_THEME_OF_TICKER.get(sym)

        # SOIC-style structured briefs
        company['growth_catalysts'] = build_growth_catalysts(company)
        company['commitments'] = build_commitments(company)

        # Data completeness flag
        company['has_concall'] = bool(company['es_concall_summary'] or company['ss_highlights'])
        company['has_full_ai'] = bool(company['es_verdict'] and company['es_ai_tag']
                                       and company['es_bsh'])
        companies.append(company)
    return companies


# ---------- SCORING ----------
def compute_conviction(c, latest_date):
    """
    v3 conviction formula — collapses SS/ES correlation, adds signal stack,
    applies confluence multiplier, adds freshness decay.

    Base components (0-100 each), then weighted sum, then multiplier:
      Fundamentals      25%   PAT YoY, OPM ∆bps, Rev YoY, BSH
      Sentiment (avg)   20%   avg of ES ECS + SS Quality (they correlate 0.64)
      Guidance          15%   Guidance Move + PEAD + Forward Metrics presence
      Momentum          15%   latest score
      Momentum trend     5%   5-day change component
      Signal Stack      10%   weighted count of 26 scans stock appears on
      Price confirm      5%   post-result move
      Confluence stamp   5%   ES verdict + SS sentiment + AI tag agreement
    Multiplier: 0.85 (disagreement) to 1.10 (strong agreement + guidance raised)
    Freshness: 1.0 for results ≤ 15 days old, linear decay to 0.85 at 45 days
    """
    parts = {}
    # --- Fundamentals composite ---
    fund = (
        0.35 * norm_pct_to_100(c['pat_yoy'], cap_at=100) +
        0.25 * norm_pct_to_100((c['opm_yoy_bps'] or 0) / 10, cap_at=100) +  # bps → pct
        0.20 * norm_pct_to_100(c['rev_yoy'], cap_at=50) +
        0.20 * bsh_to_score(c['es_bsh'])
    )
    parts['fundamentals'] = round(fund, 1)

    # --- Sentiment (avg of ES + SS, since correlated 0.64) ---
    ss_q, es_e = c['ss_quality'], c['es_ecs']
    if ss_q is not None and es_e is not None:
        sent = (ss_q + es_e) / 2
    elif es_e is not None:
        sent = es_e
    elif ss_q is not None:
        sent = ss_q
    else:
        sent = 50
    parts['sentiment'] = round(sent, 1)

    # --- Guidance composite ---
    gscore = guidance_to_score(c.get('es_guidance_move'))
    if c.get('es_pead') is not None:
        gscore = 0.6 * gscore + 0.4 * (50 + c['es_pead'] * 5)  # PEAD -10..+10 → 0..100
    # Bonus for having any forward metrics
    if c.get('es_forward_metrics'):
        gscore = min(100, gscore + 5)
    parts['guidance'] = round(gscore, 1)

    # --- Momentum ---
    mom = c.get('momentum') or 50
    parts['momentum'] = round(mom, 1)
    mom_delta = c.get('momentum_change_5d') or 0
    # 5-day change: -20 → 0, +20 → 100
    mom_trend = clamp(50 + mom_delta * 2.5, 0, 100)
    parts['momentum_trend'] = round(mom_trend, 1)

    # --- Signal Stack ---
    # weighted count → score. 0 → 40 (neutral-negative), 5 → 65, 10+ → 85+
    w = c.get('sig_weighted') or 0
    sig = clamp(40 + w * 4.5, 0, 100)
    parts['signal_stack'] = round(sig, 1)

    # --- Price confirmation ---
    pm = c.get('es_price_move')
    if pm is None:
        price = 50
    else:
        price = clamp(50 + pm * 3, 0, 100)  # ±16% → 0-100
    parts['price'] = round(price, 1)

    # --- Confluence stamp: are the three sources directionally aligned? ---
    ss_sent = c.get('ss_sentiment')
    es_tag = c.get('es_ai_tag')
    ver = c.get('es_verdict')
    positives = sum([
        1 if ss_sent == 'Bullish' else 0,
        1 if es_tag in ('Fantastic', 'Good') else 0,
        1 if ver == 'BEAT' else 0,
    ])
    negatives = sum([
        1 if ss_sent == 'Bearish' else 0,
        1 if es_tag == 'Weak' else 0,
        1 if ver == 'MISS' else 0,
    ])
    if positives >= 3: conf_stamp, mult = 100, 1.10
    elif positives >= 2 and negatives == 0: conf_stamp, mult = 85, 1.05
    elif positives >= 1 and negatives == 0: conf_stamp, mult = 65, 1.00
    elif positives == 0 and negatives == 0: conf_stamp, mult = 50, 0.98
    elif negatives >= 2: conf_stamp, mult = 15, 0.85
    else: conf_stamp, mult = 35, 0.90
    parts['confluence'] = conf_stamp
    parts['multiplier'] = mult

    # Base weighted score
    base = (
        0.25 * parts['fundamentals'] +
        0.20 * parts['sentiment'] +
        0.15 * parts['guidance'] +
        0.15 * parts['momentum'] +
        0.05 * parts['momentum_trend'] +
        0.10 * parts['signal_stack'] +
        0.05 * parts['price'] +
        0.05 * parts['confluence']
    )
    # Freshness decay based on result_date
    freshness = 1.0
    if c.get('result_date'):
        try:
            rd = pd.to_datetime(c['result_date'], format='mixed', errors='coerce')
            if pd.notna(rd) and latest_date is not None:
                days_old = max(0, (latest_date - rd).days)
                if days_old <= 15: freshness = 1.0
                elif days_old >= 45: freshness = 0.85
                else: freshness = 1.0 - 0.15 * ((days_old - 15) / 30)
        except Exception:
            pass
    parts['freshness'] = round(freshness, 3)

    final = base * mult * freshness
    return round(final, 2), parts


# ---------- MAIN ----------
def build(data_dir: Path, out_path: Path, snapshot_dir: Path | None = None):
    src = load_sources(data_dir)
    signal_stack = build_signal_stack(src['ss_scans'])
    momentum = build_company_momentum(src['ss_const'], src['ss_hist'])
    valuation = build_valuation_enrichment(src['ss_scans'])
    companies = build_companies(src, momentum, signal_stack, valuation)
    print(f"[build] Valuation coverage: P/E {len(valuation['pe'])}, D/E {len(valuation['de'])}, "
          f"ROCE {len(valuation['roce'])}")
    print(f"[build] {len(companies)} company rows assembled")

    # Determine latest result date for freshness anchor
    try:
        dates = pd.to_datetime([c['result_date'] for c in companies
                               if c.get('result_date')], errors='coerce')
        latest_date = dates.max()
    except Exception:
        latest_date = pd.Timestamp.today()

    # Score all
    for c in companies:
        c['conviction'], c['parts'] = compute_conviction(c, latest_date)

    # ---- Sector-median growth benchmarks (SOIC-inspired: contextualise growth) ----
    from statistics import median as _median
    sector_bench = {}
    for sec in set(c.get('sector') for c in companies if c.get('sector')):
        peers = [c for c in companies if c.get('sector') == sec]
        rev = [c['rev_yoy'] for c in peers if c.get('rev_yoy') is not None]
        ebi = [c['ebitda_yoy'] for c in peers if c.get('ebitda_yoy') is not None]
        pat = [c['pat_yoy'] for c in peers if c.get('pat_yoy') is not None]
        sector_bench[sec] = {
            'n': len(peers),
            'rev_median': round(_median(rev), 1) if rev else None,
            'ebitda_median': round(_median(ebi), 1) if ebi else None,
            'pat_median': round(_median(pat), 1) if pat else None,
        }
    # Attach vs-sector deltas
    for c in companies:
        b = sector_bench.get(c.get('sector'), {})
        c['sector_bench'] = b
        c['rev_vs_sector'] = (round(c['rev_yoy'] - b['rev_median'], 1)
                              if c.get('rev_yoy') is not None and b.get('rev_median') is not None else None)
        c['pat_vs_sector'] = (round(c['pat_yoy'] - b['pat_median'], 1)
                              if c.get('pat_yoy') is not None and b.get('pat_median') is not None else None)

    # --- Top Picks: must have all three sources + full AI + conviction ---
    picks_universe = [
        c for c in companies
        if c.get('has_full_ai')
        and c.get('ss_quality') is not None
        and c.get('momentum') is not None
        and c.get('es_verdict') in ('BEAT', 'IN_LINE')
        and c.get('parts', {}).get('multiplier', 1) >= 1.0
    ]
    picks_universe.sort(key=lambda x: x['conviction'], reverse=True)
    top_picks = picks_universe[:30]
    print(f"[build] Top picks universe: {len(picks_universe)}, showing top {len(top_picks)}")

    # --- Fast Growers view — SOIC/Stockscans "50%+ PAT, 25%+ Rev" bar ---
    # Only among companies that clear meaningful quality gates
    fast_growers = [
        c for c in companies
        if c.get('fast_grower')
        and c.get('has_full_ai')
        and c.get('es_verdict') in ('BEAT', 'IN_LINE')
        and c.get('es_bsh') in ('STRONG', 'STABLE')
        and (c.get('es_ecs') or 0) >= 55
    ]
    fast_growers.sort(key=lambda x: (x.get('pat_yoy') or 0), reverse=True)
    fast_growers = fast_growers[:40]

    # --- SOIC Preset picks: rev>15%, PAT>20%, mcap>10K Cr, D/E<4, P/E<35 ---
    soic_picks = [c for c in companies if c.get('soic_pass') and c.get('has_full_ai')]
    soic_picks.sort(key=lambda x: x['conviction'], reverse=True)
    soic_picks = soic_picks[:40]
    print(f"[build] Fast Growers: {len(fast_growers)}  ·  SOIC preset: {len(soic_picks)}")

    # --- Avoid Board: symmetric red flags ---
    avoid = [
        c for c in companies
        if c.get('has_full_ai')
        and c.get('es_verdict') == 'MISS'
        and c.get('es_bsh') in ('WEAK', 'STRESSED')
        and (c.get('es_ecs') or 100) < 45
    ]
    # Sort by "worst" — lowest conviction
    avoid.sort(key=lambda x: x['conviction'])
    avoid = avoid[:30]
    print(f"[build] Avoid board: {len(avoid)}")

    # --- Contradictions: SS and ES disagree; annotate with return + "who was right" ---
    contras = []
    for c in companies:
        ss_s = c.get('ss_sentiment')
        es_t = c.get('es_ai_tag')
        ver = c.get('es_verdict')
        ss_q = c.get('ss_quality')
        es_e = c.get('es_ecs')
        if not (ss_q is not None and es_e is not None):
            continue
        # SS view: Bullish/Bearish/Neutral. ES view: composite of AI tag + verdict.
        ss_bull = ss_s == 'Bullish'; ss_bear = ss_s == 'Bearish'
        es_bull = es_t in ('Fantastic', 'Good') or ver == 'BEAT'
        es_bear = es_t == 'Weak' or ver == 'MISS'
        categorical_flip = (ss_bull and es_bear) or (ss_bear and es_bull)
        div = es_e - ss_q
        score_gap = abs(div) >= 25
        if not (categorical_flip or score_gap):
            continue
        # Who was right? Use post-result price move as the arbiter
        pm = c.get('es_price_move')
        who = '—'
        if pm is not None and categorical_flip:
            if (ss_bull and pm > 2) or (ss_bear and pm < -2):
                who = 'AI1'
            elif (es_bull and pm > 2) or (es_bear and pm < -2):
                who = 'AI2'
            elif abs(pm) < 2:
                who = 'Draw'
            else:
                who = 'AI2' if es_bull == (pm > 0) else 'AI1'
        contras.append({
            'ticker': c['ticker'], 'company': c['company'], 'sector': c.get('sector', ''),
            'ss_sentiment': ss_s or '—', 'es_ai_tag': es_t or '—', 'es_verdict': ver or '',
            'ss_quality': ss_q, 'es_ecs': es_e,
            'divergence': round(div, 1),
            'flip': categorical_flip,
            'price_move': pm,
            'who_right': who,
            'result_date': c.get('result_date', ''),
            'concall_date': c.get('concall_date', ''),
        })
    contras.sort(key=lambda x: (not x['flip'], -abs(x['divergence'])))
    # Aggregate scorecard: AI-1 vs AI-2 win rate on categorical flips
    scorecard = {'AI1': 0, 'AI2': 0, 'Draw': 0, 'unknown': 0}
    for r in contras:
        if not r['flip']: continue
        w = r['who_right']
        scorecard[w if w in scorecard else 'unknown'] += 1
    print(f"[build] Contradictions flagged: {len(contras)}")

    # --- Sector rotation: current status + 1M change ---
    idx = src['ss_idx'].fillna('')
    ind = src['ss_ind'].fillna('')

    def norm_bucket(df):
        rows = []
        for _, r in df.iterrows():
            rows.append({
                'name': str(r.get(df.columns[0], '')).strip(),
                'symbol': str(r.get('Symbol', '') or '').strip(),
                'n': int(r.get('# Companies') or 0),
                'score': safe_num(r.get('Score')),
                'change_1m': safe_num(r.get('Score Change (1M)')),
                'status': str(r.get('Status', '')).strip(),
            })
        return rows
    idx_rows = norm_bucket(idx)
    ind_rows = norm_bucket(ind)

    # Inflection screen: buckets whose 1M change is strongly positive OR whose current
    # status is outperforming AND change > 5 (breaking out) OR previously stagnant now moving
    inflections = []
    for src_type, rows in [('Index', idx_rows), ('Industry', ind_rows)]:
        for r in rows:
            if r['change_1m'] is None or r['score'] is None: continue
            if r['change_1m'] >= 10 or (r['status'] == 'outperforming' and r['change_1m'] >= 5):
                inflections.append({**r, 'kind': src_type})
    inflections.sort(key=lambda x: x['change_1m'], reverse=True)

    # --- Sector beat-rate heat ---
    sector_stats = defaultdict(lambda: {'n': 0, 'beat': 0, 'miss': 0, 'in_line': 0})
    for c in companies:
        s = c.get('sector')
        if not s or not c.get('es_verdict'): continue
        sector_stats[s]['n'] += 1
        if c['es_verdict'] == 'BEAT': sector_stats[s]['beat'] += 1
        elif c['es_verdict'] == 'MISS': sector_stats[s]['miss'] += 1
        elif c['es_verdict'] == 'IN_LINE': sector_stats[s]['in_line'] += 1
    sector_rows = []
    for s, st in sector_stats.items():
        n = st['n']
        if n < 3: continue
        sector_rows.append({
            'name': s, 'n': n, 'beat': st['beat'], 'miss': st['miss'],
            'beat_rate': round(100 * st['beat'] / n, 1),
        })
    sector_rows.sort(key=lambda x: x['beat_rate'], reverse=True)

    # --- Coverage stats for transparency strip ---
    # IST = UTC + 5:30
    now_ist = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)
    coverage = {
        'total_results': len(src['es_res']),
        'with_ai': sum(1 for c in companies if c['has_full_ai']),
        'with_commentary': sum(1 for c in companies if c['has_concall']),
        'with_ss_quality': sum(1 for c in companies if c.get('ss_quality') is not None),
        'with_momentum': sum(1 for c in companies if c.get('momentum') is not None),
        'with_signal': sum(1 for c in companies if c.get('sig_count', 0) > 0),
        'all_three': sum(1 for c in companies if c['has_full_ai'] and
                          c.get('ss_quality') is not None and c.get('momentum') is not None),
        'total_scans': len(src['ss_scans']),
        'scan_rows': sum(len(df) for df in src['ss_scans'].values()),
        'latest_result': fmt_date(latest_date),
        'built_at': now_ist.strftime('%d %b %Y, %H:%M IST'),
        'built_short': now_ist.strftime('%d %b %Y'),
    }

    # Sector distribution of top picks (portfolio concentration)
    tp_sectors = Counter(p.get('sector', 'Uncategorized') for p in top_picks)

    # ---- Bucket → constituents map for drill-down in Sector Rotation ----
    bucket_constituents = defaultdict(list)
    for _, r in src['ss_const'].iterrows():
        key = (r['Bucket Type'], r['Bucket Name'])
        tick = strip_pfx(r['Symbol']) if pd.notna(r.get('Symbol')) else None
        if not tick: continue
        bucket_constituents[key].append({
            'ticker': tick,
            'company': str(r.get('Company Name', '') or ''),
            'score': safe_num(r.get('Score')),
            'change_1m': safe_num(r.get('Score Change (1M)')),
            'status': str(r.get('Status', '') or ''),
        })
    # Sort each bucket's constituents by score desc
    bc_out = {}
    for (bt, bn), lst in bucket_constituents.items():
        lst.sort(key=lambda x: (x['score'] or 0), reverse=True)
        bc_out[f"{bt}::{bn}"] = lst[:100]  # cap at top 100 to keep payload lean

    # SOIC universe: cross-reference their curated list against our data
    soic_universe_full = {}
    matched, unmatched = 0, []
    for theme, tickers in SOIC_UNIVERSE.items():
        rows = []
        for t in tickers:
            c = next((x for x in companies if x['ticker'] == t), None)
            if c: rows.append({'ticker': t, 'in_data': True}); matched += 1
            else: rows.append({'ticker': t, 'in_data': False}); unmatched.append(t)
        soic_universe_full[theme] = rows
    print(f"[build] SOIC universe: {matched} matched, {len(unmatched)} unmatched: {unmatched}")

    # ---- Sector-rotation actionable insights ----
    # 1. Buckets with accelerating momentum (change_1m >= +5 AND currently outperforming/accumulating)
    # 2. Buckets losing momentum (change_1m <= -5 or currently underperforming)
    # 3. Cross-reference which top picks live in HOT sectors
    hot_buckets = set()
    cold_buckets = set()
    for src_type, rows in [('Index', idx_rows), ('Industry', ind_rows)]:
        for r in rows:
            if r['change_1m'] is None or r['score'] is None: continue
            if r['change_1m'] >= 8 and r['status'] in ('outperforming', 'accumulating'):
                hot_buckets.add((src_type, r['name']))
            elif r['change_1m'] <= -5 or r['status'] == 'underperforming':
                cold_buckets.add((src_type, r['name']))
    # Map ticker -> list of buckets it sits in
    ticker_buckets = defaultdict(list)
    for _, r in src['ss_const'].iterrows():
        t = strip_pfx(r.get('Symbol')) if pd.notna(r.get('Symbol')) else None
        if t:
            ticker_buckets[t].append((r['Bucket Type'], r['Bucket Name']))
    # Mutually-exclusive classification — a stock is HOT if hot hits net-positive
    # by ≥ 2 over cold hits; COLD if cold hits net-positive by ≥ 2; else MIXED (not listed)
    picks_in_hot, picks_in_cold, picks_mixed = [], [], []
    for tp_ticker in [p['ticker'] for p in top_picks]:
        hot_hits = [b for b in ticker_buckets.get(tp_ticker, []) if b in hot_buckets]
        cold_hits = [b for b in ticker_buckets.get(tp_ticker, []) if b in cold_buckets]
        net = len(hot_hits) - len(cold_hits)
        entry_base = {
            'ticker': tp_ticker,
            'company': next((p['company'] for p in top_picks if p['ticker']==tp_ticker), ''),
        }
        if net >= 2 and hot_hits:
            entry_base['hot_sectors'] = [f"{b[0]}: {b[1]}" for b in hot_hits[:3]]
            entry_base['cold_count'] = len(cold_hits)
            picks_in_hot.append(entry_base)
        elif net <= -2 and cold_hits:
            entry_base['cold_sectors'] = [f"{b[0]}: {b[1]}" for b in cold_hits[:3]]
            entry_base['hot_count'] = len(hot_hits)
            picks_in_cold.append(entry_base)
        elif hot_hits or cold_hits:
            entry_base['hot_sectors'] = [f"{b[0]}: {b[1]}" for b in hot_hits[:2]]
            entry_base['cold_sectors'] = [f"{b[0]}: {b[1]}" for b in cold_hits[:2]]
            picks_mixed.append(entry_base)

    payload = {
        'coverage': coverage,
        'companies': companies,
        'rotation_insights': {
            'picks_in_hot': picks_in_hot,
            'picks_in_cold': picks_in_cold,
            'hot_count': len(hot_buckets),
            'cold_count': len(cold_buckets),
        },
        'top_picks': [p['ticker'] for p in top_picks],
        'fast_growers': [f['ticker'] for f in fast_growers],
        'soic_picks': [s['ticker'] for s in soic_picks],
        'soic_universe': soic_universe_full,
        'sector_bench': sector_bench,
        'soic_hist_quarters': SOIC_HISTORY_QUARTERS,
        'soic_market_history': SOIC_MARKET_HISTORY,
        'soic_sector_history': SOIC_SECTOR_HISTORY,
        'avoid': [a['ticker'] for a in avoid],
        'contradictions': contras,
        'contra_scorecard': scorecard,
        'idx_momentum': sorted(idx_rows, key=lambda x: (x['score'] or 0), reverse=True),
        'ind_momentum': sorted(ind_rows, key=lambda x: (x['score'] or 0), reverse=True),
        'bucket_constituents': bc_out,
        'inflections': inflections[:40],
        'sector_stats': sector_rows,
        'tp_sector_distribution': [{'sector': k, 'n': v} for k, v in tp_sectors.most_common()],
    }

    # Trim payload thoughtfully: cut at sentence boundary rather than mid-word
    def _trim(s, n):
        if not s or len(s) <= n: return s
        cut = s[:n]
        # try to end on the last full sentence
        for sep in ('. ', '.\n', '? ', '! '):
            idx = cut.rfind(sep)
            if idx >= n * 0.6:
                return cut[:idx+1]
        # else cut on whitespace to avoid mid-word
        idx = cut.rfind(' ')
        if idx >= n * 0.7:
            return cut[:idx] + '…'
        return cut + '…'
    for c in payload['companies']:
        c['es_result_summary'] = _trim(c.get('es_result_summary'), 500)
        c['es_concall_summary'] = _trim(c.get('es_concall_summary'), 600)
        c['es_mgmt_guidance'] = _trim(c.get('es_mgmt_guidance'), 500)
        c['es_verdict_reason'] = _trim(c.get('es_verdict_reason'), 350)
        c['es_pead_reason'] = _trim(c.get('es_pead_reason'), 350)
        # Prioritize NEGATIVE + top-2 POSITIVE for a balanced 4-item view
        ins = c.get('es_key_insights', [])
        neg = [i for i in ins if i['tag'] == 'NEGATIVE'][:2]
        pos = [i for i in ins if i['tag'] == 'POSITIVE'][:2]
        neu = [i for i in ins if i['tag'] == 'NEUTRAL'][:1]
        # Preserve original ordering but drop dupes
        picked = []
        seen = set()
        for i in ins:
            if len(picked) >= 4: break
            key = i['text'][:60]
            if key in seen: continue
            if i in neg or i in pos or (len(picked) < 4 and i in neu):
                picked.append(i); seen.add(key)
        c['es_key_insights'] = picked[:4]
        for i in c['es_key_insights']:
            i['text'] = _trim(i['text'], 260)
        # Trim catalyst bodies too
        for cat in c.get('growth_catalysts', []):
            cat['body'] = _trim(cat['body'], 220)

    # ---- Trend deltas — compare to prior snapshot ----
    prior, prior_date = (None, None)
    if snapshot_dir:
        prior, prior_date = load_prior_snapshot(snapshot_dir)
    tp_delta, tp_drop = compute_deltas(payload['top_picks'], prior, 'top_picks')
    fg_delta, fg_drop = compute_deltas(payload['fast_growers'], prior, 'fast_growers')
    av_delta, av_drop = compute_deltas(payload['avoid'], prior, 'avoid')
    sp_delta, sp_drop = compute_deltas(payload['soic_picks'], prior, 'soic_picks')
    compute_conviction_delta(payload['companies'], prior)
    # Attach entry reasons to each company (for "why in the list")
    for c in payload['companies']:
        c['entry_reason'] = entry_reason(c)
    by_tick = {c['ticker']: c for c in payload['companies']}
    prior_conv = (prior or {}).get('conviction_by_ticker', {}) if prior else {}
    def _explain_dropouts(tickers):
        out = []
        for t in tickers:
            c = by_tick.get(t, {})
            out.append({
                'ticker': t,
                'company': c.get('company', ''),
                'reason': drop_reason(c, prior_conv),
                'sector': c.get('sector', ''),
            })
        return out
    def _explain_newbies(delta_map, current_list):
        out = []
        for t in current_list:
            d = delta_map.get(t, {})
            if d.get('status') != 'NEW': continue
            c = by_tick.get(t, {})
            out.append({
                'ticker': t,
                'company': c.get('company', ''),
                'reason': c.get('entry_reason'),
                'sector': c.get('sector', ''),
            })
        return out
    payload['trend'] = {
        'prior_date': prior_date,
        'top_picks': tp_delta,
        'top_picks_dropouts': _explain_dropouts(tp_drop),
        'top_picks_newbies': _explain_newbies(tp_delta, payload['top_picks']),
        'fast_growers': fg_delta,
        'fast_growers_dropouts': _explain_dropouts(fg_drop),
        'fast_growers_newbies': _explain_newbies(fg_delta, payload['fast_growers']),
        'avoid': av_delta,
        'avoid_dropouts': _explain_dropouts(av_drop),
        'avoid_newbies': _explain_newbies(av_delta, payload['avoid']),
        'soic_picks': sp_delta,
    }

    # ---- Save today's snapshot for tomorrow's build ----
    today_str = dt.date.today().isoformat()
    if snapshot_dir:
        save_snapshot(snapshot_dir, payload, today_str)
    payload['coverage']['snapshot_date'] = today_str
    payload['coverage']['prior_snapshot_date'] = prior_date

    html_out = render_html(payload)
    out_path.write_text(html_out, encoding='utf-8')
    print(f"[done] Wrote {out_path} ({len(html_out):,} chars, {len(html_out)/1024/1024:.1f} MB)")
    if prior_date:
        print(f"[trend] vs snapshot {prior_date}: {sum(1 for v in tp_delta.values() if v['status']=='NEW')} new in Top Picks, "
              f"{len(tp_drop)} dropped out")
    return payload


# ---------- HTML RENDER ----------
def render_html(payload):
    # Inline data as JSON blob, then let the JS render
    data_json = json.dumps(payload, default=str, ensure_ascii=False, separators=(',', ':'))
    # Load template
    tpl_path = Path(__file__).parent / 'template.html'
    if not tpl_path.exists():
        raise FileNotFoundError(f"Missing template.html next to build_terminal.py")
    tpl = tpl_path.read_text(encoding='utf-8')
    return tpl.replace('__DATA_JSON__', data_json)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default='.', type=Path)
    ap.add_argument('--out', default='Confluence Terminal v3.html', type=Path)
    ap.add_argument('--snapshot-dir', default=None, type=Path,
                    help='Directory of prior daily snapshots (JSON) for trend deltas. Optional.')
    args = ap.parse_args()
    build(args.data_dir, args.out, args.snapshot_dir)
