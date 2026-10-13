# Round 1: classic swing setups on the 2018-2026 panel, identical portfolio rules (10 slots, 0.3%/side, gauge scaling).
import sys, json
from swing import *
U = univ(); T200 = C > sma(200); UP = sma(50) > sma(200); RS = rs_rank(126); R1 = C.pct_change(fill_method=None)
prev = lambda df, k=1: df.shift(k)
SET = {}
# --- mean reversion (Connors) ---
SET['RSI2<10 above 200-day, exit close>5-day avg'] = dict(entry=U & T200 & (rsi(2) < 10), score=-rsi(2), exit_sig=C > sma(5), max_hold=10)
SET['RSI2<5 above 200-day, exit close>5-day avg'] = dict(entry=U & T200 & (rsi(2) < 5), score=-rsi(2), exit_sig=C > sma(5), max_hold=10)
SET['RSI2<10 in RS leaders (top 30%)'] = dict(entry=U & T200 & (RS >= 0.7) & (rsi(2) < 10), score=RS, exit_sig=C > sma(5), max_hold=10)
SET['3-day drop >=6% in RS leaders'] = dict(entry=U & T200 & UP & (RS >= 0.8) & (ret(3) <= -0.06), score=RS, exit_sig=C > sma(5), max_hold=10)
# --- breakouts ---
tight20 = (hi(20) / lo(20) - 1)
SET['New 52-week closing high, tight 20-day base (<15%)'] = dict(entry=U & (C > prev(hi(250))) & (prev(tight20) < 0.15), score=RS, stop=0.08, exit_sig=C < ema(20), min_hold=5, max_hold=60)
SET['New 52-week closing high (any)'] = dict(entry=U & (C > prev(hi(250))), score=RS, stop=0.08, exit_sig=C < ema(20), min_hold=5, max_hold=60)
SET['50-day high breakout in uptrend (Darvas)'] = dict(entry=U & UP & T200 & (C > prev(hi(50))) & (prev(hi(50)) / prev(lo(50)) - 1 < 0.25), score=RS, stop=0.08, exit_sig=C < ema(20), min_hold=5, max_hold=60)
SET['Donchian 20-day breakout, exit 10-day low (Turtle)'] = dict(entry=U & (C > prev(hi(20))), score=RS, stop=0.10, exit_sig=C < prev(lo(10)), max_hold=60)
SET['Trend template + 20-day high (Minervini)'] = dict(entry=U & T200 & UP & (sma(50) > sma(150)) & (C / hi(250) >= 0.75) & (C / lo(250) >= 1.3) & (RS >= 0.7) & (C > prev(hi(20))) & (prev(tight20) < 0.12),
                                                     score=RS, stop=0.07, exit_sig=C < sma(50), min_hold=5, max_hold=60)
# --- pullbacks in leaders ---
touch20 = (L <= ema(20)) & (C > ema(20)) & (R1 > 0)
SET['Pullback to 20-day EMA in leader, stop signal-day low, +10% target'] = dict(entry=U & T200 & UP & (RS >= 0.8) & touch20 & (prev(C, 10) < C * 1.1), score=RS, stop_px=L * 0.995, target=0.10, max_hold=15)
touch50 = (L <= sma(50)) & (C > sma(50)) & (R1 > 0)
SET['Pullback to 50-day average in leader'] = dict(entry=U & T200 & (RS >= 0.8) & touch50, score=RS, stop_px=L * 0.99, target=0.12, max_hold=20)
# --- momentum burst (Bonde) ---
SET['4% up day after a quiet day, hold 5'] = dict(entry=U & (R1 >= 0.04) & (prev(R1).abs() < 0.02) & T200, score=RS, stop_px=L * 0.995, max_hold=5)
SET['4% up day after a quiet day, hold 5, leaders only'] = dict(entry=U & (R1 >= 0.04) & (prev(R1).abs() < 0.02) & T200 & (RS >= 0.8), score=RS, stop_px=L * 0.995, max_hold=5)
# --- short-term reversal ---
SET['Weekly losers among leaders (5-day ret bottom 10%)'] = dict(entry=U & T200 & (RS >= 0.7) & (ret(5).where(U).rank(axis=1, pct=True) <= 0.1), score=-ret(5), max_hold=5)

if __name__ == "__main__" and False:
    out = []
    for name, kw in SET.items():
        for lag in (1, 0):
            D, T = simulate(lag=lag, **kw); s = stats(D, T, f'{name} | {"next close" if lag else "same close"}'); s['lag'] = lag; out.append(s)
            print(fmt(s), flush=True)
    json.dump(out, open(rs2.S + '/data/swing_r1.json', 'w'), indent=1)
