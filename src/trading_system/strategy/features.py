"""Technical features per bar (CLAUDE.md §9, implementation plan task 4.2).

`feature_rows(bars)` returns one dict per bar, or None while any indicator is
still warming up. Row i uses only bars 0..i (no look-ahead), so rows can be used
directly as ML features for a decision taken at the close of bar i.
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_system.broker.contracts import Bar
from trading_system.strategy import indicators as ind

FEATURE_NAMES: tuple[str, ...] = (
    "return_1", "return_3", "return_5", "return_10",
    "ema_20", "ema_50", "ema_200",
    "distance_to_ema_50", "distance_to_ema_200",
    "rsi", "macd", "macd_signal", "macd_hist",
    "atr", "atr_percent", "adx",
    "spread", "hour", "day_of_week",
)


def feature_rows(bars: Sequence[Bar]) -> list[dict[str, float] | None]:
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    ema20, ema50, ema200 = ind.ema(closes, 20), ind.ema(closes, 50), ind.ema(closes, 200)
    rsi = ind.rsi(closes, 14)
    macd_line, macd_sig, macd_hist = ind.macd(closes)
    atr = ind.atr(highs, lows, closes, 14)
    adx, _, _ = ind.adx(highs, lows, closes, 14)

    rows: list[dict[str, float] | None] = []
    for i, bar in enumerate(bars):
        values = (ema20[i], ema50[i], ema200[i], rsi[i], macd_line[i], macd_sig[i],
                  macd_hist[i], atr[i], adx[i])
        if i < 10 or any(v is None for v in values):
            rows.append(None)
            continue
        e20, e50, e200, r, m, ms, mh, a, dx = (float(v) for v in values if v is not None)
        c = closes[i]
        rows.append({
            "return_1": c / closes[i - 1] - 1,
            "return_3": c / closes[i - 3] - 1,
            "return_5": c / closes[i - 5] - 1,
            "return_10": c / closes[i - 10] - 1,
            "ema_20": e20,
            "ema_50": e50,
            "ema_200": e200,
            "distance_to_ema_50": c / e50 - 1,
            "distance_to_ema_200": c / e200 - 1,
            "rsi": r,
            "macd": m,
            "macd_signal": ms,
            "macd_hist": mh,
            "atr": a,
            "atr_percent": a / c,
            "adx": dx,
            "spread": float(bar.spread_points),
            "hour": float(bar.time.hour),
            "day_of_week": float(bar.time.weekday()),
        })
    return rows
