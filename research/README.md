# Research v3 — Results Leaders (13 Oct 2026)

Full interactive report: Claude artifact "Results Leaders Research" (linked from the page, section "Why these rules").
Raw numbers: `research/v3/results/*.json`. Code: `research/v3/` (set `CT_WORK` to a work dir holding `data/`, `secrets/`).

## 1. Data census — what can carry a strategy test
| Source | Size / history | Verdict |
|---|---|---|
| EquiSense quarterly results | 77,879 filings, FY22 → Q2 FY27; ~1,600 cos/season from Oct 2022 | **Core signal** |
| EquiSense concalls | 24,427 calls, FY22 → today | Guidance CUT = exclusion |
| Adjusted daily closes (BP feed) | 1,874 stocks × 2,168 days from 2018 | Reaction, trend, liquidity, returns |
| StockScans breadth | daily since 2009 | Market gauge (2 of 3 votes) |
| StockScans index series | 62 indices weekly, 5 y | Benchmarks. **BSE 500 / Sensex have a 19-month gap** (Apr 2024 → Nov 2025) → use Nifty 50 / Smallcap 250 |
| EquiSense smart money | 3,319 deals since Sep 2025 | Event study only |
| EquiSense filings (orders, capex, updates) | Oct 2025 → today | Event study only |
| StockScans PIT ratio panels | 18 holdings snapshots since Apr 2025 | Too short |
| StockScans concall scores | 2 quarters | Too short |
Never backtest EquiSense `ecsScore`, `marketCap`, `pe` (today's values in history).

## 2. Method (identical plumbing for every idea)
Tradeable results (mcap PIT ≥ ₹1,000 cr; 20-day median turnover ≥ ₹5 cr where volume exists; filed ≤ 120 days after quarter end),
16,097 events Oct 2022 → Oct 2026. Every rank is against the **previous season** only. Entry at the close, within 10 sessions of the
first post-result close; 15 slots; 60-session hold; 0.3% per side; new buys sized by the 3-vote gauge. Inside each pool the order is
random (median of 20 runs), so the league measures the idea. Window 1 Jan 2023 → 12 Oct 2026.
Simulator fix 13 Oct: at gauge 0 no buys (earlier runs created zero-weight placeholder positions; all numbers below are post-fix).

## 3. League table (per year / worst fall)
| Pool | CAGR | Worst fall | 2023 | 2024 | 2025 | 2026 YTD |
|---|---|---|---|---|---|---|
| **Composite top 10% (model pool)** | **35.0%** | −19.8% | 69.1 | 48.9 | −6.7 | 29.0 |
| Relative strength top 10% (6-month run) | 31.1% | −19.1% | 64.1 | 34.2 | −3.5 | 30.7 |
| Minervini trend template + PAT ≥ 20% | 26.2% | −20.0% | 58.0 | 33.4 | −6.4 | 22.8 |
| CAN SLIM core (PAT ≥25, rev ≥20, ≤15% off high) | 24.3% | −19.5% | 34.3 | 47.0 | −7.8 | 22.6 |
| Biggest result-day reaction (episodic pivot) | 23.6% | −24.4% | 60.2 | 35.9 | −12.1 | 15.0 |
| Raised guidance | 19.1% | −15.0% | 39.2 | 20.2 | −2.9 | 17.4 |
| Any result, random (baseline) | 18.0% | −19.4% | 54.9 | 21.5 | −4.7 | 3.8 |
| Cheapest 20% P/E | 17.0% | −22.8% | | | | |
| Biggest EPS surprise (PEAD) | 16.6% | −23.0% | | | | |
| Consistent compounder | 16.1% | −18.9% | | | | |
| GARP (PEG < 1) | 14.1% | −23.2% | | | | |
| **Guidance CUT** | **0.1%** | −26.4% | 19.6 | 2.0 | −14.1 | −3.0 |
Benchmarks same window: equal-weight liquid universe 25.3% (−25.2%), Nifty Smallcap 250 18.0% (−25.3%), Nifty 50 5.7% (−15.5%).
Score-ordered model path (what the live engine does): 35.2% / −22.4%. Without gauge: 45.4% / −23.3%.

## 4. Key findings
- Score sorts the future monotonically: decile 1 → 10 average 60-session excess −4.0% → +2.1%; beat-market share 32% → 44%.
- Parts: growth alone 18.8% (≈ random), trend alone 25.9%, reaction alone 24.7%; combined 35.0%.
- Gauge (random-order medians): none 43.9% / −28.1% (2025 −10.2%); **scale 35.0% / −19.8%**; skip-at-0 only 33.3% / −35.0%.
- Hold: 20 → 10.9%, 40 → 19.9%, **60 → 32.1% (−19.5%)**, 120 → 32.1% (−16.1%); 50-day-average exit 17.6%; hold-through-next-good-result 28.7%. 60 vs 120 is a tie in this sample — first thing to revisit with more data.
- Order inside the top 10% barely matters → treat each season as a basket.
- Short-history hints (20-session excess, ~1 year): bulk/block buys ≥ 0.5% mcap +2.8% median, 54% beat (n 139); non-promoter insider selling −4.3% median, 29% beat (n 265); order-win filings no edge (31% beat when marked positive).

## 5. Validation of the live SQL engine
Replay 1 Jan 2025 → 12 Oct 2026: engine ₹1.2135 vs Python ₹1.2005; worst fall −19.1% vs −17.5%; 75 trades each; 14/15 current holdings identical.
Top-decile set Q1 FY26: all 120 engine picks inside the research set of 128.

## 6. Caveats
4 years, mostly rising small caps; survivorship in pre-2025 prices (set = stocks liquid today); pre-2025 liquidity rests on mcap only;
0.3%/side costs, no impact model; buys bunch in results season (15 slots fill in 2–3 weeks).
