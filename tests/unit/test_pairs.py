"""pairs-v001 statistics and rules (ADR 0007)."""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from trading_system.broker.contracts import Bar
from trading_system.strategy.pairs import (
    PairsParams,
    PairsStrategy,
    adf_t,
    engle_granger_crit_5pct,
    ols,
)

T0 = datetime(2024, 1, 1, tzinfo=UTC)
H1 = timedelta(hours=1)
SMALL = PairsParams(beta_window=60, beta_every=1, z_window=30, atr_period=5,
                    coint_filter=False)


class Noise:
    """Deterministic N(0, 1) stream (LCG + Box-Muller): reproducible, no `random` module."""

    def __init__(self, seed: int) -> None:
        self._state = seed + 1
        self._spare: Iterator[float] = iter(())

    def _uniform(self) -> float:
        self._state = (6364136223846793005 * self._state + 1442695040888963407) % 2**64
        return ((self._state >> 11) + 1) / (2**53 + 1)

    def gauss(self, mu: float, sigma: float) -> float:
        z = next(self._spare, None)
        if z is None:
            u1, u2 = self._uniform(), self._uniform()
            radius = math.sqrt(-2 * math.log(u1))
            z = radius * math.cos(2 * math.pi * u2)
            self._spare = iter((radius * math.sin(2 * math.pi * u2),))
        return mu + sigma * z


def bars_from(closes: list[float], skip: frozenset[int] = frozenset()) -> list[Bar]:
    return [Bar(time=T0 + H1 * i, open=c, high=c * 1.001, low=c * 0.999, close=c,
                tick_volume=1, spread_points=0) for i, c in enumerate(closes) if i not in skip]


def synthetic(n: int = 200, seed: int = 1) -> tuple[list[float], list[float]]:
    """NZD random walk; AUD = NZD^1.2 x stationary noise (a cointegrated pair)."""
    r = Noise(seed)
    lb = [math.log(0.60)]
    for _ in range(n - 1):
        lb.append(lb[-1] + r.gauss(0, 0.002))
    noise = [0.0]
    for _ in range(n - 1):
        noise.append(0.5 * noise[-1] + r.gauss(0, 0.001))
    la = [0.1 + 1.2 * b + e for b, e in zip(lb, noise, strict=True)]
    return [math.exp(v) for v in la], [math.exp(v) for v in lb]


class TestStatistics:
    def test_ols_recovers_a_line(self) -> None:
        x = [0.1 * i for i in range(10)]
        alpha, beta = ols(x, [2.0 + 3.0 * v for v in x])
        assert alpha == pytest.approx(2.0)
        assert beta == pytest.approx(3.0)

    def test_ols_rejects_constant_regressor(self) -> None:
        with pytest.raises(ValueError, match="constant"):
            ols([1.0] * 5, [1.0, 2.0, 3.0, 4.0, 5.0])

    def test_adf_separates_stationary_from_random_walk(self) -> None:
        r = Noise(0)
        stationary, walk = [0.0], [0.0]
        for _ in range(999):
            stationary.append(0.5 * stationary[-1] + r.gauss(0, 1))
            walk.append(walk[-1] + r.gauss(0, 1))
        crit = engle_granger_crit_5pct(998)
        assert adf_t(stationary) < crit
        assert adf_t(walk) > crit

    def test_mackinnon_critical_value(self) -> None:
        assert engle_granger_crit_5pct(998) == pytest.approx(-3.3423, abs=1e-4)


class TestStrategy:
    def test_z_matches_a_direct_computation(self) -> None:
        a, b = synthetic()
        s = PairsStrategy(SMALL, {"AUDUSD": bars_from(a), "NZDUSD": bars_from(b)})
        k = 150
        state = s.state(T0 + H1 * k)
        assert state is not None
        alpha, beta = ols([math.log(v) for v in b[k - 59:k + 1]],
                          [math.log(v) for v in a[k - 59:k + 1]])
        assert state.beta == pytest.approx(beta)
        spreads = [math.log(a[j]) - beta * math.log(b[j]) for j in range(k - 29, k + 1)]
        mean = sum(spreads) / 30
        std = math.sqrt(sum((x - mean) ** 2 for x in spreads) / 29)
        assert state.z == pytest.approx((spreads[-1] - mean) / std)
        assert state.beta == pytest.approx(1.2, abs=0.2)

    def test_only_common_hours_are_used(self) -> None:
        a, b = synthetic()
        s = PairsStrategy(SMALL, {"AUDUSD": bars_from(a, frozenset({100})),
                                  "NZDUSD": bars_from(b)})
        assert s.state(T0 + H1 * 100) is None
        assert len(s.times) == 199

    def test_no_state_during_warm_up(self) -> None:
        a, b = synthetic()
        s = PairsStrategy(SMALL, {"AUDUSD": bars_from(a), "NZDUSD": bars_from(b)})
        assert s.entry(T0 + H1 * 58) == (0, "indicators_not_ready")
        assert s.state(T0 + H1 * 59) is not None

    def test_entry_direction_follows_z(self) -> None:
        a, b = synthetic()
        a[150] *= 1.02  # AUD jumps: spread expensive -> short spread
        s = PairsStrategy(SMALL, {"AUDUSD": bars_from(a), "NZDUSD": bars_from(b)})
        state = s.state(T0 + H1 * 150)
        assert state is not None and state.z > 2
        assert s.entry(T0 + H1 * 150) == (-1, None)
        a[150] /= 1.02 ** 2  # AUD drops instead: long spread
        s = PairsStrategy(SMALL, {"AUDUSD": bars_from(a), "NZDUSD": bars_from(b)})
        assert s.entry(T0 + H1 * 150) == (1, None)

    def test_inside_band_holds(self) -> None:
        a, b = synthetic()
        s = PairsStrategy(SMALL, {"AUDUSD": bars_from(a), "NZDUSD": bars_from(b)})
        holds = {s.entry(t)[1] for t in s.times[60:] if abs(s.state(t).z) < 2}  # type: ignore[union-attr]
        assert holds == {"z_inside_band"}

    def test_cointegration_filter_blocks_unrelated_series(self) -> None:
        params = SMALL.model_copy(update={"coint_filter": True, "entry_z": 0.01,
                                          "beta_window": 200})
        r = Noise(3)
        a, b = [0.7], [0.6]
        for _ in range(599):  # two independent random walks
            a.append(a[-1] * math.exp(r.gauss(0, 0.003)))
            b.append(b[-1] * math.exp(r.gauss(0, 0.003)))
        unrelated = PairsStrategy(params, {"AUDUSD": bars_from(a), "NZDUSD": bars_from(b)})
        ca, cb = synthetic(600, seed=3)
        related = PairsStrategy(params, {"AUDUSD": bars_from(ca), "NZDUSD": bars_from(cb)})

        def blocked(s: PairsStrategy) -> float:
            reasons = [s.entry(t)[1] for t in s.times[200:]]
            return reasons.count("not_cointegrated") / len(reasons)

        # Short windows produce spurious cointegration now and then, hence a majority test.
        assert blocked(unrelated) > 0.5
        assert blocked(related) == 0.0

    def test_exit_rules(self) -> None:
        a, b = synthetic()
        s = PairsStrategy(SMALL, {"AUDUSD": bars_from(a), "NZDUSD": bars_from(b)})
        t = T0 + H1 * 150
        state = s.state(t)
        assert state is not None
        k = state.index
        crossed = state.z >= 0
        assert s.should_exit(t, +1, k) is (crossed or abs(state.z) >= 4)
        assert s.should_exit(t, -1, k) is (not crossed or abs(state.z) >= 4)
        assert s.should_exit(t, +1, k - SMALL.max_bars)  # time stop
