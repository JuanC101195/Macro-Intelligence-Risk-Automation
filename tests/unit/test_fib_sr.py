"""fibsr-xau-v001 (ADR 0011): swings, candles, stop management and no look-ahead."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.fixtures.bars import START, random_walk
from trading_system.broker.contracts import Bar
from trading_system.domain import Side
from trading_system.strategy import fib_sr
from trading_system.strategy.fib_sr import FibSrParams, FibSrStrategy

# Looser than the hypothesis so a short random walk produces setups to compare.
TEST_PARAMS = FibSrParams(zigzag_atr=2.0, m5_zigzag_atr=2.0, min_leg_atr=3.0)


def _m5(n: int, seed: int = 11) -> list[Bar]:
    walk = random_walk(n, seed=seed, start_price=2000.0, vol=0.0015)
    return [b.model_copy(update={"time": START + timedelta(minutes=5 * i)})
            for i, b in enumerate(walk)]


def _h1(m5: list[Bar]) -> list[Bar]:
    out = []
    for k in range(0, len(m5) - 11, 12):
        chunk = m5[k:k + 12]
        out.append(Bar(time=chunk[0].time, open=chunk[0].open,
                       high=max(b.high for b in chunk), low=min(b.low for b in chunk),
                       close=chunk[-1].close, tick_volume=1, spread_points=0))
    return out


def _bar(o: float, h: float, lo: float, c: float, i: int = 0) -> Bar:
    return Bar(time=START + timedelta(minutes=5 * i), open=o, high=h, low=lo, close=c,
               tick_volume=1, spread_points=0)


def test_zigzag_confirms_swings_only_after_the_reversal() -> None:
    v = [0, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5, 6]
    values = [float(x) for x in v]
    pivots = fib_sr.zigzag(values, values, [1.0] * len(v), mult=2.0)
    assert pivots == [fib_sr.Pivot("H", 5.0, 5, 7), fib_sr.Pivot("L", 1.0, 9, 11)]


def test_fractals_need_both_wings() -> None:
    assert fib_sr.fractals([1, 2, 3, 9, 3, 2, 1], 3, highs=True) == [(3, 9)]
    assert fib_sr.fractals([5, 4, 3, 1, 3, 4, 5], 3, highs=False) == [(3, 1)]


def test_zones_group_touches_within_tolerance() -> None:
    zones = fib_sr._zones([(0, 10.0), (5, 10.3), (9, 12.0)], tol=0.5, min_touches=2)
    assert (10.0, 10.3) in zones
    assert all(hi < 12.0 for _, hi in zones)


@pytest.mark.parametrize(("prev", "bar", "short", "expected"), [
    ((10, 11, 9.9, 10.8), (10.9, 11.0, 9.5, 9.8), True, True),   # bearish engulfing
    ((10, 10.2, 9.9, 10.1), (10.0, 11.0, 9.9, 10.05), True, True),  # long upper wick
    ((10, 10.2, 9.9, 10.1), (10.0, 10.3, 9.0, 10.25), True, False),  # wick on the wrong side
    ((10.8, 11, 9.9, 10.0), (9.9, 11.0, 9.9, 10.9), False, True),  # bullish engulfing
])
def test_trigger_candles(prev: tuple[float, ...], bar: tuple[float, ...], short: bool,
                         expected: bool) -> None:
    assert fib_sr._trigger(_bar(*prev), _bar(*bar, i=1), short, 2.0) is expected


def test_stop_locks_half_r_at_one_r_then_trails() -> None:
    m5 = _m5(3000)
    strategy = FibSrStrategy(TEST_PARAMS, {"XAUUSD": m5}, {"XAUUSD": _h1(m5)})
    bar = m5[2000].model_copy(update={"close": 2021.0})
    entry_time = m5[1500].time
    # Not yet +1 R (R = 20): nothing moves.
    assert strategy.stop_update("XAUUSD", m5[2000].model_copy(update={"close": 2010.0}),
                                "buy", entry_time, 2000.0, 1980.0, 1980.0) is None
    # +1 R reached: lock +0.5 R.
    assert strategy.stop_update("XAUUSD", bar, "buy", entry_time, 2000.0, 1980.0,
                                1980.0) == pytest.approx(2010.0)
    # Once locked, only a confirmed M5 swing low after the entry and above the stop.
    trailed = strategy.stop_update("XAUUSD", bar, "buy", entry_time, 2000.0, 1980.0, 2010.0)
    pivots = strategy._m5_pivots["XAUUSD"]
    if trailed is not None:
        assert trailed > 2010.0
        assert any(p.kind == "L" and p.price == trailed and p.idx >= 1500 and p.confirm <= 2000
                   for p in pivots)


def test_setups_never_use_future_bars() -> None:
    m5 = _m5(6000)
    h1 = _h1(m5)
    full = FibSrStrategy(TEST_PARAMS, {"XAUUSD": m5}, {"XAUUSD": h1})
    assert full._setups, "the test data must produce setups"
    cut = 4000
    cut_close = m5[cut].time + timedelta(minutes=5)
    short_m5 = m5[:cut + 1]
    short_h1 = [b for b in h1 if b.time + timedelta(hours=1) <= cut_close]
    partial = FibSrStrategy(TEST_PARAMS, {"XAUUSD": short_m5}, {"XAUUSD": short_h1})
    before = {k: v for k, v in full._setups.items() if k[1] <= m5[cut].time}
    assert partial._setups == before
    assert all(s.side in (Side.LONG, Side.SHORT) for s in before.values())
