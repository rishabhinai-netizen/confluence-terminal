# Research log — what predicts returns after Indian results (12 Oct 2026)

Data: EquiSense results (7 quarters, Q4 FY25 → Q2 FY27, ~35k), EquiSense concalls (~11k), EquiSense smart money
(bulk/block/SAST: last 90 days; insider: longer), adjusted daily prices for 1,864 liquid NSE/BSE stocks (Jan 2025 →)
from the Breakout Playbook feed. Scripts here are re-runnable (`CT_SCRATCH` = folder with `secrets/` and `data/`).

## Method (identical in Python `rs.py` and SQL `010_engine.sql`)
- Entry = close of the first session strictly after the calendar day the information became public.
- Excess return = stock return − equal-weight universe return (stocks with ≥ Rs 2 cr daily turnover), same sessions.
- Reaction = entry close / close of the session before the announcement day.
- Results filed > 120 days after quarter end are re-filings → excluded (3.6% of rows).
- Rules chosen on Apr 2025–Mar 2026; checked on Apr–Oct 2026. Baseline for every rule = all events of its family.

## Kept (live on the page)
| Rule | Evidence (excess vs equal-weight market) |
|---|---|
| **Drift buy**: PAT YoY ≥ 25%, revenue YoY ≥ 15%, reaction ≥ +3% | 20d: 52.7% beat vs 43.0% baseline, median +0.6% vs −1.5%. 60d: 51.6% vs 42.5%. Held in all three sub-periods (A1 Apr–Sep 25, A2 Oct 25–Mar 26 falling market, B Apr–Oct 26). Edge grows with reaction size (3% → 5% → 8%: 60d median +1.4 → +2.6 → +3.9). |
| Market gate (equal-weight index vs its 50-day average) | Drift buys in up-trends: 60d 55.8% beat, +2.6%; in down-trends 44.6%, −1.7%. |
| Late entry | Edge unchanged for entries up to 8 sessions after the first post-result close → 10-session window. |
| Stops | −8% stop hit in 53% of cases, mean unchanged, hit-rate falls to 41%; −12% stop hit 39%. → small size, wide stop. |
| Avoid: missed (or PAT ≤ −10%) and fell ≥ 3% | 60d 38.6% beat, median −5.0% (baseline −2.7%); worst in up-markets (−8.2%). |
| Avoid: balance sheet STRESSED (EquiSense) | 60d 21.8% beat, median −13.0%. |
| Avoid: guidance CUT | 60d 33.0% beat, −5.9%. Missed own guidance: 34.9%, −8.5% (n 43, early). |
| Red flag: same-day buy-and-sell bulk churn ≥ 0.1% of mcap | 20d 40.2% beat, −5.5% (deal data from Jul 2026 only). |
| Red flag: insider selling by non-promoters | 20d 28.2% beat, −4.0%. |
| In play: bulk buy or sell ≥ 0.1% of mcap | 20d 56.4% beat, +3.1% (early; Jul 2026 →). |

## Tested and dropped
- **EquiSense ECS score**: identical across all past quarters for 100% of 3,097 companies → it is today's score, not
  point-in-time. Any backtest using it (including the old v1–v8 conviction score) used future information. Display only.
- Old build-8 conviction score: its own walk-forward showed top quartile *under*-performing bottom (−2.0% at 20d).
- EquiSense verdict / PEAD label inside the drift set: no added edge (Fantastic/Good vs Neutral similar). Labels exist
  for only ~14% of results before Apr 2026.
- Guidance RAISED: no edge (50% beat at 20d, −0.2% at 60d). Promoter buying: no edge.
- Stock momentum (3m, 6m-1m) and industry momentum: top vs bottom quintile inconsistent month to month (2025–26).
- New concall reads (candor, tone, earnings quality, analyst sentiment): only exist from Q2 FY27 → forward tracking only.

## Preliminary: StockScans scans (NOT yet rules)
Membership at 6 month-ends (30 Apr – 30 Sep 2026), forward 20 sessions vs equal-weight market; all liquid stocks on the
same dates: 40.9% beat, median −2.1%. One mostly-rising regime, and monthly members overlap, so samples are not independent.
- Led: Early Growth & Relative Strength 57.8% / +1.6% (n 374), Index Outperformance 1Y 55.0% / +1.6%, Industry
  Outperformance 1Y 55.4% / +1.6%, Explosive Growth 55.3% / +1.5%, Super Growth 55.5% / +1.2%, Buoyant Growth 53.3% / +1.0%.
- No better than average or worse: Cyclone 40.5% / −2.4%, Volume Rocketing 40.3% / −2.3%, Bulk Block Deals 39.9% / −2.4%,
  Weekly Trend Twist 34.1% / −2.8%, The Consolidators 36.6% / −3.7%, Bombed Out IPO 39.4% / −1.9%.
- StockScans' own PEAD scan: 44.0% / −2.0% (n 50) — weaker than our drift rule.
Next: weekly snapshots back to Apr 2025 (covers the Oct 25–Mar 26 fall), study *new entries* not membership, then decide.
Full table: run the snippet in HANDOVER §4.1 or `data/scan_prelim_20d.csv` in the scratch folder.

## Open
- StockScans 37 pre-built scans: point-in-time membership history being pulled (`pull_ss_scanhist.py`, month-ends first,
  then week-ends back to Apr 2025; StockScans throttles at ~50–300 calls per window). Next: event study on scan *entries*.
- StockScans concall result score / sentiment / congrats count: only 2 quarters exist (202606, 202609) → forward tracking.
- StockEdge regime layer (491 scans mapped in Aug) — later.
