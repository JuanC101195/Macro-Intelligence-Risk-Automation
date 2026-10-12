from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.fixtures.risk_fixtures import NOW, FakeQuotes, account, position, spec
from trading_system.broker.contracts import Tick
from trading_system.domain import Side, Timeframe
from trading_system.execution.order_intent import make_intent_id
from trading_system.risk.circuit_breaker import FileCircuitBreaker
from trading_system.risk.contracts import ExposureSnapshot, RiskLimits
from trading_system.risk.engine import DefaultRiskEngine
from trading_system.risk.exposure import currency_legs, risk_to_stop, trading_day_start
from trading_system.strategy.signals import Signal

BAR_TIME = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
LIMITS = RiskLimits(max_risk_per_trade=0.0025, max_daily_loss=0.02, max_open_positions=1,
                    max_consecutive_losses=3, max_spread_points=30, max_slippage_points=10,
                    max_trades_per_day=5)
TICK = Tick(time=NOW, bid=1.08240, ask=1.08250, spread_points=10)


def long_signal(**overrides: Any) -> Signal:
    data: dict[str, Any] = {
        "signal_id": "sig", "symbol": "EURUSD", "timeframe": "M15", "bar_time": BAR_TIME,
        "side": "LONG", "confidence": 0.7, "technical_score": 100, "macro_regime": "mixed",
        "entry_ref": 1.08250, "stop_loss": 1.08050, "take_profit": 1.08650,
        "strategy_version": "baseline-v001", "reasons": ("ema_trend_up",),
    }
    data.update(overrides)
    return Signal(**data)


def short_signal() -> Signal:
    return long_signal(side="SHORT", entry_ref=1.08240, stop_loss=1.08440, take_profit=1.07840)


def exposure(**overrides: Any) -> ExposureSnapshot:
    data: dict[str, Any] = {"open_positions": (), "realized_pnl_today": 0.0,
                            "unrealized_pnl": 0.0, "consecutive_losses": 0, "trades_today": 0,
                            "day_start_equity": 10_000.0}
    data.update(overrides)
    return ExposureSnapshot(**data)


@pytest.fixture
def breaker(tmp_path: Path) -> FileCircuitBreaker:
    return FileCircuitBreaker(tmp_path / "breaker.json", clock=lambda: NOW)


def engine(breaker: FileCircuitBreaker, limits: RiskLimits = LIMITS,
           quotes: FakeQuotes | None = None) -> DefaultRiskEngine:
    return DefaultRiskEngine(limits, breaker, quotes or FakeQuotes(), mode="paper")


def evaluate(breaker: FileCircuitBreaker, *, signal: Signal | None = None, acc: Any = None,
             sp: Any = None, tick: Tick = TICK, exp: ExposureSnapshot | None = None,
             limits: RiskLimits = LIMITS, quotes: FakeQuotes | None = None) -> Any:
    return engine(breaker, limits, quotes).evaluate(
        signal or long_signal(), acc or account(), sp or spec(), tick, exp or exposure())


class TestApproval:
    def test_long_intent(self, breaker: FileCircuitBreaker) -> None:
        d = evaluate(breaker)
        assert d.approved
        i = d.intent
        assert i.side == "buy"
        assert i.entry_price == TICK.ask
        assert i.stop_loss == 1.08050
        assert i.take_profit == 1.08650
        assert i.volume == 0.12
        assert i.risk_amount == pytest.approx(24.0)
        assert i.mode == "paper"
        assert d.risk_percent == pytest.approx(0.0024)
        assert i.intent_id == make_intent_id("baseline-v001", "EURUSD", Timeframe.M15,
                                             BAR_TIME, Side.LONG)

    def test_short_intent_uses_bid(self, breaker: FileCircuitBreaker) -> None:
        d = evaluate(breaker, signal=short_signal())
        assert d.approved
        assert d.intent.side == "sell"
        assert d.intent.entry_price == TICK.bid

    def test_usdjpy(self, breaker: FileCircuitBreaker) -> None:
        sig = long_signal(symbol="USDJPY", entry_ref=150.010, stop_loss=149.710,
                          take_profit=150.610)
        tick = Tick(time=NOW, bid=150.000, ask=150.010, spread_points=10)
        d = evaluate(breaker, signal=sig, sp=spec("USDJPY"), tick=tick)
        assert d.approved, d.rejections
        assert d.intent.volume == 0.12


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"signal": long_signal(side="HOLD", hold_reasons=("no_setup",), entry_ref=None,
                                stop_loss=None, take_profit=None)}, "not_a_trade_signal"),
        ({"sp": spec("GBPUSD")}, "symbol_mismatch"),
        ({"sp": spec(trade_allowed=False)}, "symbol_not_tradeable"),
        ({"tick": TICK.model_copy(update={"spread_points": 31})}, "spread_too_wide"),
        ({"exp": exposure(open_positions=(position("GBPUSD"),))}, "max_open_positions"),
        ({"exp": exposure(trades_today=5)}, "max_trades_per_day"),
    ],
)
def test_gate_rejections(breaker: FileCircuitBreaker, kwargs: dict[str, Any], reason: str) -> None:
    d = evaluate(breaker, **kwargs)
    assert not d.approved
    assert reason in d.rejections
    assert d.intent is None


def test_short_not_allowed(breaker: FileCircuitBreaker) -> None:
    d = evaluate(breaker, signal=short_signal(), sp=spec(short_allowed=False))
    assert "short_not_allowed" in d.rejections


def test_same_symbol_exposure(breaker: FileCircuitBreaker) -> None:
    limits = LIMITS.model_copy(update={"max_open_positions": 3})
    d = evaluate(breaker, limits=limits, exp=exposure(open_positions=(position("EURUSD"),)))
    assert "max_symbol_exposure" in d.rejections


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"acc": account(trade_mode="real")}, "account_not_demo"),
        ({"exp": exposure(consecutive_losses=3)}, "max_consecutive_losses"),
        ({"exp": exposure(realized_pnl_today=-150.0, unrealized_pnl=-60.0)}, "daily_loss_limit"),
    ],
)
def test_unsafe_states_trip_the_breaker(breaker: FileCircuitBreaker, kwargs: dict[str, Any],
                                        reason: str) -> None:
    d = evaluate(breaker, **kwargs)
    assert reason in d.rejections
    assert breaker.is_open()
    assert breaker.state().reason == reason
    # Once open, everything is rejected until a human resets it.
    assert "circuit_breaker_open" in evaluate(breaker).rejections


def test_open_position_without_stop_trips_breaker(breaker: FileCircuitBreaker) -> None:
    limits = LIMITS.model_copy(update={"max_open_positions": 3})
    exp = exposure(open_positions=(position("GBPUSD", stop_loss=None),))
    d = evaluate(breaker, limits=limits, exp=exp)
    assert not d.approved
    assert breaker.state().reason == "open_position_without_stop"


class TestPrices:
    def test_price_already_past_stop(self, breaker: FileCircuitBreaker) -> None:
        tick = Tick(time=NOW, bid=1.08030, ask=1.08040, spread_points=10)
        assert "price_beyond_stop_or_target" in evaluate(breaker, tick=tick).rejections

    def test_entry_drift(self, breaker: FileCircuitBreaker) -> None:
        # Ask jumped 12 pips: real stop distance 32 pips vs 20 planned (> +50%).
        tick = Tick(time=NOW, bid=1.08360, ask=1.08370, spread_points=10)
        assert "entry_drifted" in evaluate(breaker, tick=tick).rejections

    def test_stop_too_close_for_broker(self, breaker: FileCircuitBreaker) -> None:
        d = evaluate(breaker, sp=spec(stops_level_points=500))
        assert "stop_too_close" in d.rejections


class TestPortfolio:
    def test_worst_case_daily_loss_budget(self, breaker: FileCircuitBreaker) -> None:
        # Already lost 190 of a 200 budget: a 24 USD risk would allow 214 in the worst case.
        d = evaluate(breaker, exp=exposure(realized_pnl_today=-190.0))
        assert "daily_loss_budget" in d.rejections
        assert not breaker.is_open()  # not hit yet, just no room for this trade

    def test_open_risk_counts_toward_budget(self, breaker: FileCircuitBreaker) -> None:
        limits = LIMITS.model_copy(update={"max_open_positions": 3})
        big = position("GBPUSD", volume=1.0, open_price=1.2700, stop_loss=1.2520)  # 1800 USD
        d = evaluate(breaker, limits=limits, exp=exposure(open_positions=(big,)))
        assert "daily_loss_budget" in d.rejections

    def test_same_direction_currency_exposure(self, breaker: FileCircuitBreaker) -> None:
        limits = LIMITS.model_copy(update={"max_open_positions": 3})
        long_gbpusd = position("GBPUSD", volume=0.12, open_price=1.2700, stop_loss=1.2680)
        d = evaluate(breaker, limits=limits, exp=exposure(open_positions=(long_gbpusd,)))
        assert "currency_exposure_USD" in d.rejections

    def test_opposite_direction_currency_is_allowed(self, breaker: FileCircuitBreaker) -> None:
        limits = LIMITS.model_copy(update={"max_open_positions": 3})
        short_gbpusd = position("GBPUSD", side="sell", volume=0.12, open_price=1.2700,
                                stop_loss=1.2720)
        d = evaluate(breaker, limits=limits, exp=exposure(open_positions=(short_gbpusd,)))
        assert d.approved, d.rejections


class TestBrokerChecks:
    def test_insufficient_margin(self, breaker: FileCircuitBreaker) -> None:
        d = evaluate(breaker, acc=account(margin_free=100.0))
        assert "insufficient_margin" in d.rejections

    def test_wrong_tick_value_is_caught(self, breaker: FileCircuitBreaker) -> None:
        # Spec claims 2 USD per tick; MT5's own profit calculation disagrees.
        d = evaluate(breaker, sp=spec(tick_value=2.0))
        assert "tick_value_mismatch" in d.rejections

    def test_volume_below_minimum(self, breaker: FileCircuitBreaker) -> None:
        d = evaluate(breaker, acc=account(equity=100.0, balance=100.0))
        assert d.rejections == ("volume_below_min",)


class TestExposureHelpers:
    @pytest.mark.parametrize(
        ("now", "expected"),
        [
            (datetime(2026, 7, 15, 20, 30, tzinfo=UTC), datetime(2026, 7, 14, 21, 0, tzinfo=UTC)),
            (datetime(2026, 7, 15, 21, 30, tzinfo=UTC), datetime(2026, 7, 15, 21, 0, tzinfo=UTC)),
            (datetime(2026, 1, 15, 22, 30, tzinfo=UTC), datetime(2026, 1, 15, 22, 0, tzinfo=UTC)),
            (datetime(2026, 1, 15, 21, 30, tzinfo=UTC), datetime(2026, 1, 14, 22, 0, tzinfo=UTC)),
        ],
    )
    def test_trading_day_starts_at_17_new_york(self, now: datetime, expected: datetime) -> None:
        assert trading_day_start(now) == expected

    def test_trading_day_needs_tz(self) -> None:
        naive = datetime(2026, 1, 1)  # noqa: DTZ001
        with pytest.raises(ValueError):
            trading_day_start(naive)

    def test_currency_legs(self) -> None:
        assert currency_legs("EURUSD", "buy") == {"EUR": 1, "USD": -1}
        assert currency_legs("USDJPY", "sell") == {"USD": -1, "JPY": 1}

    def test_risk_to_stop(self) -> None:
        assert risk_to_stop(position(), FakeQuotes()) == pytest.approx(24.0)
        assert risk_to_stop(position(stop_loss=None), FakeQuotes()) is None


def test_engine_cannot_emit_live_intents(breaker: FileCircuitBreaker) -> None:
    live_engine = DefaultRiskEngine(LIMITS, breaker, FakeQuotes(), mode="live")  # type: ignore[arg-type]
    sig, acc, sp, exp = long_signal(), account(), spec(), exposure()
    with pytest.raises(ValidationError, match="mode"):
        live_engine.evaluate(sig, acc, sp, TICK, exp)


class TestRiskFraction:
    """Pair legs (ADR 0007) may ask for less than the per-trade limit, never more."""

    def test_smaller_fraction_sizes_down(self, breaker: FileCircuitBreaker) -> None:
        d = engine(breaker).evaluate(long_signal(), account(), spec(), TICK, exposure(),
                                     risk_fraction=0.00125)
        assert d.approved
        assert d.intent.volume == 0.06  # half of the 0.12 lots at the full 0.25 %

    @pytest.mark.parametrize("fraction", [0.0, -0.001, 0.0026])
    def test_out_of_range_is_rejected(self, breaker: FileCircuitBreaker, fraction: float) -> None:
        d = engine(breaker).evaluate(long_signal(), account(), spec(), TICK, exposure(),
                                     risk_fraction=fraction)
        assert not d.approved
        assert d.rejections == ("risk_fraction_out_of_range",)
