"""Deterministic synthetic M15 bars for strategy and indicator tests."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from trading_system.broker.contracts import Bar

START = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)  # a Monday


def random_walk(n: int, seed: int = 7, start_price: float = 1.1, drift: float = 0.0,
                vol: float = 0.0004) -> list[Bar]:
    rng = random.Random(seed)  # noqa: S311 - reproducible test data, not cryptography
    bars: list[Bar] = []
    price = start_price
    for i in range(n):
        o = round(price, 5)
        c = round(max(1e-4, o * (1 + drift + rng.gauss(0, vol))), 5)
        # Round first, then widen high/low so rounding never breaks OHLC containment.
        h = max(round(max(o, c) * (1 + abs(rng.gauss(0, vol / 2))), 5), o, c)
        low = min(round(min(o, c) * (1 - abs(rng.gauss(0, vol / 2))), 5), o, c)
        bars.append(Bar(time=START + timedelta(minutes=15 * i), open=o, high=h, low=low,
                        close=c, tick_volume=100, spread_points=12))
        price = c
    return bars


def ohlc(highs: list[float], lows: list[float], closes: list[float]) -> list[Bar]:
    return [
        Bar(time=START + timedelta(minutes=15 * i), open=c, high=h, low=lo, close=c,
            tick_volume=1, spread_points=0)
        for i, (h, lo, c) in enumerate(zip(highs, lows, closes, strict=True))
    ]
