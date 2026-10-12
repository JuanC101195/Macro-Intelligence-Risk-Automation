"""GMM regimes (ADR 0008): features, EM, refit schedule, no look-ahead, breakout filter."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from tests.fixtures.noise import Noise
from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.domain import Side, Timeframe
from trading_system.macro.macro_context import MacroContext
from trading_system.strategy.breakout import BreakoutParams, BreakoutStrategy
from trading_system.strategy.regimes import (
    RegimeParams,
    features,
    fit_mixture,
    refit_dates,
    trend_flags,
)
from trading_system.strategy.signals import MarketState

H4 = timedelta(hours=4)
SMALL = RegimeParams(components=2, feature_window=10, train_years=1)


def h4_bars(closes: list[float], t0: datetime) -> list[Bar]:
    return [Bar(time=t0 + H4 * i, open=c, high=c * 1.0005, low=c * 0.9995, close=c,
                tick_volume=1, spread_points=0) for i, c in enumerate(closes)]


def alternating_regimes(n: int, seed: int = 5) -> list[float]:
    """Blocks of 60 bars: strong drift (trend) then pure noise (range)."""
    r = Noise(seed)
    price, out = 1.0, []
    for i in range(n):
        drift = 0.002 if (i // 60) % 2 == 0 else 0.0
        price *= math.exp(drift + r.gauss(0, 0.001))
        out.append(price)
    return out


class TestFeatures:
    def test_straight_line_is_pure_trend(self) -> None:
        closes = [1.0 * 1.001 ** i for i in range(20)]
        closes[15] *= 1.0001  # avoid a zero-variance window
        vol, er = features(closes, 10)[19]  # type: ignore[misc]
        assert er == pytest.approx(1.0)
        assert vol < 0

    def test_zigzag_has_no_efficiency(self) -> None:
        closes = [1.0 if i % 2 == 0 else 1.01 for i in range(21)]
        point = features(closes, 10)[20]
        assert point is not None
        assert point[1] == pytest.approx(0.0)

    def test_warm_up_and_flat_prices_are_none(self) -> None:
        feats = features([1.0] * 20, 10)
        assert all(f is None for f in feats)


class TestMixture:
    def test_recovers_two_separated_clusters(self) -> None:
        r = Noise(1)
        a = [(r.gauss(-2, 0.3), r.gauss(0.2, 0.05)) for _ in range(300)]
        b = [(r.gauss(1, 0.3), r.gauss(0.8, 0.05)) for _ in range(100)]
        m = fit_mixture(a + b, RegimeParams(components=2))
        assert sorted(m.weights) == pytest.approx([0.25, 0.75], abs=0.01)
        trend = m.trend_component
        assert m.label((1.0, 0.8)) == trend
        assert m.label((-2.0, 0.2)) != trend

    def test_is_deterministic(self) -> None:
        r = Noise(2)
        pts = [(r.gauss(0, 1), r.gauss(0, 1)) for _ in range(200)]
        first = fit_mixture(pts, SMALL)
        second = fit_mixture(list(pts), SMALL)
        assert first == second

    def test_needs_enough_points(self) -> None:
        with pytest.raises(ValueError, match="not enough"):
            fit_mixture([(0.0, 0.0)] * 5, RegimeParams())


class TestSchedule:
    def test_refit_dates_are_january_and_july(self) -> None:
        dates = refit_dates(datetime(2020, 3, 1, tzinfo=UTC), datetime(2021, 8, 1, tzinfo=UTC))
        assert [d.strftime("%Y-%m") for d in dates] == ["2020-07", "2021-01", "2021-07"]

    def test_labels_never_use_the_future(self) -> None:
        t0 = datetime(2019, 1, 1, tzinfo=UTC)
        closes = alternating_regimes(4_000)
        full = trend_flags(h4_bars(closes, t0), SMALL, t0)
        cut = datetime(2020, 7, 1, tzinfo=UTC)
        n = next(i for i in range(len(closes)) if t0 + H4 * i >= cut)
        changed = closes[:n] + [c * 1.3 for c in closes[n:]]  # different future
        other = trend_flags(h4_bars(changed, t0), SMALL, t0)
        before = {t: v for t, v in full.items() if t < cut}
        assert before
        assert before == {t: v for t, v in other.items() if t < cut}

    def test_needs_a_complete_training_window(self) -> None:
        t0 = datetime(2019, 3, 1, tzinfo=UTC)  # 1-year window complete only for 2020-07
        flags = trend_flags(h4_bars(alternating_regimes(3_000), t0), SMALL, t0)
        assert min(flags) >= datetime(2020, 7, 1, tzinfo=UTC)

    def test_trend_blocks_are_labelled_trend(self) -> None:
        t0 = datetime(2019, 1, 1, tzinfo=UTC)
        bars = h4_bars(alternating_regimes(4_000), t0)
        flags = trend_flags(bars, SMALL, t0)
        trend_block = [flags[b.time] for i, b in enumerate(bars)
                       if b.time in flags and (i // 60) % 2 == 0 and i % 60 >= 15]
        range_block = [flags[b.time] for i, b in enumerate(bars)
                       if b.time in flags and (i // 60) % 2 == 1 and i % 60 >= 15]
        assert sum(trend_block) / len(trend_block) > 0.8
        assert sum(range_block) / len(range_block) < 0.2


class TestBreakoutFilter:
    T0 = datetime(2024, 1, 1, tzinfo=UTC)

    def decide(self, regime: dict[str, dict[datetime, bool]] | None) -> tuple[str, ...]:
        closes = [1.0] * 60 + [1.05]  # last close breaks the 55-bar channel
        bars = [Bar(time=self.T0 + H4 * i, open=c, high=c + 0.001, low=c - 0.001, close=c,
                    tick_volume=1, spread_points=0) for i, c in enumerate(closes)]
        params = BreakoutParams(version="regime-h4-v001", timeframe=Timeframe.H4)
        strategy = BreakoutStrategy(params, {"EURUSD": bars}, regime=regime)
        spec = SymbolSpec(symbol="EURUSD", digits=5, point=0.00001, tick_size=0.00001,
                          tick_value=1.0, contract_size=100_000, volume_min=0.01,
                          volume_max=100, volume_step=0.01, stops_level_points=0,
                          freeze_level_points=0, currency_base="EUR", currency_profit="USD",
                          currency_margin="EUR", trade_allowed=True, short_allowed=True)
        tick = Tick(time=bars[-1].time + H4, bid=1.05, ask=1.05012, spread_points=12)
        signal = strategy.decide(None, bars[-1], tick, spec, MacroContext.unknown(bars[-1].time),
                                 MarketState(has_open_position=False, risk_blocked=False),
                                 None, "EURUSD")
        assert signal.timeframe is Timeframe.H4
        return (signal.side.value, *signal.hold_reasons)

    def test_without_filter_the_breakout_trades(self) -> None:
        assert self.decide(None) == (Side.LONG.value,)

    def test_trend_regime_lets_it_through(self) -> None:
        t = self.T0 + H4 * 60
        assert self.decide({"EURUSD": {t: True}}) == (Side.LONG.value,)

    def test_other_regime_or_no_model_holds(self) -> None:
        t = self.T0 + H4 * 60
        assert self.decide({"EURUSD": {t: False}}) == (Side.HOLD.value, "regime_not_trend")
        assert self.decide({"EURUSD": {}}) == (Side.HOLD.value, "regime_not_ready")
