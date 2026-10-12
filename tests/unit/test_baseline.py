from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.fixtures.bars import random_walk
from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.domain import Side
from trading_system.macro.macro_context import MacroContext
from trading_system.strategy.baseline import (
    BaselineParams,
    BaselineStrategy,
    IndicatorSnapshot,
    decide,
)
from trading_system.strategy.signals import MarketState

P = BaselineParams()
BAR = Bar(time=datetime(2026, 10, 14, 13, 30, tzinfo=UTC), open=1.0820, high=1.0830,
          low=1.0815, close=1.0825, tick_volume=100, spread_points=10)
CLOSE_TIME = BAR.time + timedelta(minutes=15)
TICK = Tick(time=CLOSE_TIME + timedelta(seconds=3), bid=1.0825, ask=1.0826, spread_points=10)
SPEC = SymbolSpec(
    symbol="EURUSD", digits=5, point=1e-5, tick_size=1e-5, tick_value=1.0,
    contract_size=100_000, volume_min=0.01, volume_max=100, volume_step=0.01,
    stops_level_points=0, freeze_level_points=0, currency_base="EUR", currency_profit="USD",
    currency_margin="EUR", trade_allowed=True, short_allowed=True,
)
FREE = MarketState(has_open_position=False, risk_blocked=False)


def macro(regime: str = "mixed", stale: bool = False) -> MacroContext:
    return MacroContext(timestamp=CLOSE_TIME, risk_regime=regime, confidence=0.5,  # type: ignore[arg-type]
                        source_health=1.0, data_stale=stale)


LONG_SNAP = IndicatorSnapshot(
    close=1.0825, ema_fast=1.0800, ema_slow=1.0750, rsi=45.0, rsi_prev=38.0,
    rsi_window_min=33.0, rsi_window_max=48.0, macd_hist=0.0002, atr=0.0010, adx=30.0,
)
SHORT_SNAP = IndicatorSnapshot(
    close=1.0700, ema_fast=1.0750, ema_slow=1.0800, rsi=55.0, rsi_prev=62.0,
    rsi_window_min=50.0, rsi_window_max=67.0, macd_hist=-0.0002, atr=0.0010, adx=30.0,
)


def run(snap: IndicatorSnapshot | None = LONG_SNAP, **kw: Any) -> Any:
    args: dict[str, Any] = {"snap": snap, "last_bar": BAR, "tick": TICK, "spec": SPEC,
                            "macro": macro(), "state": FREE, "p": P, "symbol": "EURUSD"}
    args.update(kw)
    return decide(**args)


class TestEntries:
    def test_long(self) -> None:
        s = run()
        assert s.side is Side.LONG
        assert s.entry_ref == TICK.ask  # buys fill at the ask
        assert s.stop_loss == pytest.approx(TICK.ask - 1.5 * 0.0010)
        assert s.take_profit == pytest.approx(TICK.ask + 3.0 * 0.0010)
        assert s.technical_score == 100
        assert 0.5 <= s.confidence <= 1.0
        assert s.hold_reasons == ()

    def test_short(self) -> None:
        s = run(SHORT_SNAP)
        assert s.side is Side.SHORT
        assert s.entry_ref == TICK.bid  # sells fill at the bid
        assert s.stop_loss == pytest.approx(TICK.bid + 1.5 * 0.0010)
        assert s.take_profit == pytest.approx(TICK.bid - 3.0 * 0.0010)

    def test_prices_rounded_to_symbol_digits(self) -> None:
        s = run(replace(LONG_SNAP, atr=0.00123456))
        assert s.stop_loss == round(s.stop_loss, 5)

    def test_signal_is_deterministic(self) -> None:
        first, second = run(), run()
        assert first == second

    def test_confidence_scales_with_adx(self) -> None:
        weak, strong = run(replace(LONG_SNAP, adx=20.0)), run(replace(LONG_SNAP, adx=45.0))
        assert weak.confidence == 0.5
        assert strong.confidence == 1.0

    def test_unknown_macro_only_penalizes_when_not_required(self) -> None:
        s = run(macro=macro("unknown", stale=True))
        assert s.side is Side.LONG
        assert s.confidence == pytest.approx(run().confidence * 0.8)
        assert "macro_unknown_penalty" in s.reasons


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"ema_fast": 1.0700}, "no_setup"),        # trend down
        ({"close": 1.0790}, "no_setup"),           # below EMA50
        ({"rsi_window_min": 41.0}, "no_setup"),    # no pullback below 40
        ({"rsi": 37.0}, "no_setup"),               # not recovered above 40
        ({"rsi_prev": 46.0}, "no_setup"),          # RSI not rising
        ({"macd_hist": -0.0001}, "no_setup"),
        ({"adx": 15.0}, "no_setup"),
        ({"adx": None}, "indicators_not_ready"),
    ],
)
def test_each_long_condition_is_required(change: dict[str, Any], reason: str) -> None:
    s = run(replace(LONG_SNAP, **change))
    assert s.side is Side.HOLD
    assert reason in s.hold_reasons


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"snap": None, "last_bar": None}, "insufficient_data"),
        ({"tick": TICK.model_copy(update={"time": CLOSE_TIME - timedelta(seconds=1)})},
         "bar_not_closed"),
        ({"tick": TICK.model_copy(update={"time": CLOSE_TIME + timedelta(minutes=31)})},
         "stale_data"),
        ({"tick": TICK.model_copy(update={"spread_points": 31})}, "spread_too_wide"),
        ({"state": MarketState(has_open_position=True, risk_blocked=False)}, "position_open"),
        ({"state": MarketState(has_open_position=False, risk_blocked=True)}, "risk_blocked"),
        ({"spec": SPEC.model_copy(update={"trade_allowed": False})}, "symbol_not_tradeable"),
        ({"macro": macro("risk_off")}, "macro_contradiction"),
        ({"macro": macro("unknown", stale=True), "p": BaselineParams(macro_required=True)},
         "macro_unavailable"),
    ],
)
def test_hold_conditions(kwargs: dict[str, Any], reason: str) -> None:
    s = run(**kwargs)
    assert s.side is Side.HOLD
    assert reason in s.hold_reasons
    assert s.stop_loss is None


def test_risk_on_blocks_short_and_short_permissions() -> None:
    assert "macro_contradiction" in run(SHORT_SNAP, macro=macro("risk_on")).hold_reasons
    no_short = SPEC.model_copy(update={"short_allowed": False})
    assert "short_not_allowed" in run(SHORT_SNAP, spec=no_short).hold_reasons
    assert run(SHORT_SNAP, p=BaselineParams(allow_short=False)).side is Side.HOLD


@pytest.mark.parametrize(
    ("snap", "regime", "allowed"),
    [
        ("long", "risk_on", True), ("long", "mixed", False), ("long", "unknown", False),
        ("short", "risk_off", True), ("short", "mixed", False), ("short", "risk_on", False),
    ],
)
def test_macro_confirmation_variant(snap: str, regime: str, allowed: bool) -> None:
    p = BaselineParams(macro_require_confirmation=True)
    s = run(LONG_SNAP if snap == "long" else SHORT_SNAP, p=p, macro=macro(regime))
    assert (s.side is not Side.HOLD) is allowed


def test_all_hold_reasons_reported_together() -> None:
    s = run(tick=TICK.model_copy(update={"spread_points": 50}),
            state=MarketState(has_open_position=True, risk_blocked=True))
    assert {"spread_too_wide", "position_open", "risk_blocked"} <= set(s.hold_reasons)


def test_no_setup_explains_best_side() -> None:
    s = run(replace(LONG_SNAP, adx=10.0))
    assert "adx_trending=no" in s.reasons
    assert s.technical_score == 80


class TestStrategyOnBars:
    def _tick_after(self, bars: list[Bar]) -> Tick:
        t = bars[-1].time + timedelta(minutes=15, seconds=2)
        c = bars[-1].close
        return Tick(time=t, bid=c, ask=round(c + 0.0001, 5), spread_points=10)

    def test_insufficient_bars(self) -> None:
        bars = random_walk(P.min_bars - 1)
        s = BaselineStrategy().evaluate(bars, self._tick_after(bars), SPEC, macro(), FREE)
        assert s.hold_reasons == ("insufficient_data",)

    def test_runs_on_real_length_series_and_is_deterministic(self) -> None:
        bars = random_walk(P.min_bars + 50, seed=5)
        strat = BaselineStrategy()
        a = strat.evaluate(bars, self._tick_after(bars), SPEC, macro(), FREE)
        b = strat.evaluate(bars, self._tick_after(bars), SPEC, macro(), FREE)
        assert a == b
        assert a.strategy_version == "baseline-v001"
        assert a.bar_time == bars[-1].time
