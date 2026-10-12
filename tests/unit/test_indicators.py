from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.fixtures.bars import random_walk
from trading_system.strategy import indicators as ind

# Wilder RSI worked example published by StockCharts ("RSI" ChartSchool article).
STOCKCHARTS_CLOSES = [
    44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245, 45.8433, 46.0826,
    45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028, 46.0328, 46.4116, 46.2222, 45.6439,
    46.2122, 46.2521, 45.7137, 46.4515, 45.7835, 45.3548, 44.0288, 44.1783, 44.2181, 44.5672,
    43.4205, 42.6628, 43.1314,
]
STOCKCHARTS_RSI = [
    70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38,
    54.71, 50.42, 39.99, 41.46, 41.87, 45.46, 37.30, 33.08, 37.77,
]


def test_rsi_matches_published_wilder_example() -> None:
    out = ind.rsi(STOCKCHARTS_CLOSES, 14)
    assert out[:14] == [None] * 14
    assert [round(v, 2) for v in out[14:] if v is not None] == STOCKCHARTS_RSI


def test_sma_and_ema_by_hand() -> None:
    assert ind.sma([1, 2, 3, 4, 5], 2) == [None, 1.5, 2.5, 3.5, 4.5]
    # EMA(3): seed = SMA(1,2,3) = 2, alpha = 0.5
    assert ind.ema([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_atr_by_hand() -> None:
    highs, lows, closes = [10, 11, 12, 11], [9, 10, 10, 9], [9.5, 10.5, 11, 10]
    # TR = [-, 1.5, 2, 2]; ATR(2) seed = mean(1.5, 2) = 1.75; next = (1.75 + 2) / 2
    assert ind.atr(highs, lows, closes, 2) == [None, None, 1.75, 1.875]


def test_rsi_extremes() -> None:
    assert ind.rsi(list(range(1, 30)), 14)[-1] == 100.0
    assert ind.rsi([5.0] * 30, 14)[-1] == 50.0


def test_macd_relationships() -> None:
    flat = [1.2] * 60
    line, sig, hist = ind.macd(flat)
    assert line[-1] == pytest.approx(0.0)
    assert hist[-1] == pytest.approx(0.0)
    closes = [b.close for b in random_walk(200)]
    line, sig, hist = ind.macd(closes)
    for m, s, h in zip(line, sig, hist, strict=True):
        if h is not None:
            assert h == pytest.approx(m - s)  # type: ignore[operator]
    # TA-Lib convention: first histogram value at index slow + signal - 2.
    assert next(i for i, v in enumerate(hist) if v is not None) == 26 + 9 - 2


def test_adx_trend_vs_range() -> None:
    n = 120
    up_h = [1.0 + 0.001 * i for i in range(n)]
    up_l = [h - 0.0005 for h in up_h]
    adx, pdi, mdi = ind.adx(up_h, up_l, up_h, 14)
    assert next(i for i, v in enumerate(adx) if v is not None) == 2 * 14 - 1
    assert pdi[-1] > mdi[-1]  # type: ignore[operator]
    assert adx[-1] > 50  # type: ignore[operator]

    zig_c = [1.0 + (0.001 if i % 2 else -0.001) for i in range(n)]
    zig_h = [c + 0.0005 for c in zig_c]
    zig_l = [c - 0.0005 for c in zig_c]
    adx_range, _, _ = ind.adx(zig_h, zig_l, zig_c, 14)
    assert adx_range[-1] < 20  # type: ignore[operator]
    assert all(0 <= v <= 100 for v in adx if v is not None)


INDICATORS: dict[str, Callable[[list[float], list[float], list[float]], object]] = {
    "ema": lambda h, lo, c: ind.ema(c, 50),
    "rsi": lambda h, lo, c: ind.rsi(c, 14),
    "macd": lambda h, lo, c: ind.macd(c),
    "atr": lambda h, lo, c: ind.atr(h, lo, c, 14),
    "adx": lambda h, lo, c: ind.adx(h, lo, c, 14),
}


@pytest.mark.parametrize("name", list(INDICATORS))
def test_no_look_ahead(name: str) -> None:
    """Values up to bar k must not change when later bars are added."""
    bars = random_walk(400, seed=11)
    h, lo, c = [b.high for b in bars], [b.low for b in bars], [b.close for b in bars]
    fn = INDICATORS[name]
    full = fn(h, lo, c)
    for k in (60, 150, 299):
        prefix = fn(h[:k], lo[:k], c[:k])
        if isinstance(full, tuple):
            for series_full, series_prefix in zip(full, prefix, strict=True):  # type: ignore[call-overload]
                assert series_full[:k] == series_prefix
        else:
            assert full[:k] == prefix  # type: ignore[index]


def test_invalid_periods() -> None:
    with pytest.raises(ValueError):
        ind.ema([1.0], 0)
    with pytest.raises(ValueError):
        ind.macd([1.0] * 50, fast=26, slow=12)
