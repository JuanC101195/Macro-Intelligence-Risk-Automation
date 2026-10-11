from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from trading_system.broker.contracts import Bar, Tick
from trading_system.domain import Side, Timeframe
from trading_system.execution.order_intent import OrderIntent, make_intent_id
from trading_system.macro.macro_context import MacroContext
from trading_system.models.schemas import ModelRecord
from trading_system.risk.contracts import RiskDecision
from trading_system.strategy.signals import Signal

T0 = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)


def _intent(**overrides: Any) -> OrderIntent:
    data: dict[str, Any] = {
        "intent_id": make_intent_id("baseline-v001", "EURUSD", Timeframe.M15, T0, Side.LONG),
        "signal_id": "sig-1",
        "signal_bar_time": T0,
        "symbol": "EURUSD",
        "side": "buy",
        "entry_price": 1.0825,
        "stop_loss": 1.0805,
        "take_profit": 1.0865,
        "volume": 0.12,
        "risk_amount": 24.0,
        "strategy_version": "baseline-v001",
        "mode": "paper",
        "reason": "test",
    }
    data.update(overrides)
    return OrderIntent(**data)


def _signal(**overrides: Any) -> Signal:
    data: dict[str, Any] = {
        "signal_id": "sig-1",
        "symbol": "EURUSD",
        "timeframe": "M15",
        "bar_time": T0,
        "side": "LONG",
        "confidence": 0.7,
        "technical_score": 78,
        "macro_regime": "risk_on",
        "entry_ref": 1.0825,
        "stop_loss": 1.0805,
        "take_profit": 1.0865,
        "strategy_version": "baseline-v001",
    }
    data.update(overrides)
    return Signal(**data)


class TestOrderIntent:
    def test_valid_buy(self) -> None:
        assert _intent().volume == 0.12

    def test_valid_sell(self) -> None:
        intent = _intent(side="sell", stop_loss=1.0845, take_profit=1.0785)
        assert intent.side == "sell"

    def test_live_mode_cannot_be_built(self) -> None:
        with pytest.raises(ValidationError):
            _intent(mode="live")

    @pytest.mark.parametrize("missing", ["stop_loss", "take_profit", "volume", "risk_amount"])
    def test_mandatory_fields(self, missing: str) -> None:
        with pytest.raises(ValidationError):
            _intent(**{missing: None})

    def test_stop_on_wrong_side_rejected(self) -> None:
        with pytest.raises(ValidationError, match="LONG requires"):
            _intent(stop_loss=1.0835)

    def test_short_stop_on_wrong_side_rejected(self) -> None:
        with pytest.raises(ValidationError, match="SHORT requires"):
            _intent(side="sell", stop_loss=1.0805, take_profit=1.0785)

    @pytest.mark.parametrize("volume", [0, -0.1])
    def test_volume_must_be_positive(self, volume: float) -> None:
        with pytest.raises(ValidationError):
            _intent(volume=volume)

    def test_bad_intent_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="intent_id"):
            _intent(intent_id="not-an-id")

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _intent(signal_bar_time=datetime(2026, 10, 12, 14, 0))  # noqa: DTZ001

    def test_intent_id_is_deterministic(self) -> None:
        a = make_intent_id("v1", "EURUSD", Timeframe.M15, T0, Side.LONG)
        b = make_intent_id("v1", "EURUSD", Timeframe.M15, T0, Side.LONG)
        c = make_intent_id("v1", "EURUSD", Timeframe.M15, T0 + timedelta(minutes=15), Side.LONG)
        assert a == b != c
        assert len(a) == 16

    def test_is_immutable(self) -> None:
        intent = _intent()
        with pytest.raises(ValidationError):
            intent.volume = 10  # type: ignore[misc]


class TestSignal:
    def test_long_signal(self) -> None:
        assert _signal().side is Side.LONG

    def test_hold_needs_reason(self) -> None:
        with pytest.raises(ValidationError, match="hold_reasons"):
            _signal(side="HOLD")
        hold = _signal(side="HOLD", hold_reasons=("spread_too_wide",),
                       entry_ref=None, stop_loss=None, take_profit=None)
        assert hold.side is Side.HOLD

    def test_trade_signal_needs_bracket(self) -> None:
        with pytest.raises(ValidationError, match="require"):
            _signal(stop_loss=None)

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            _signal(confidence=1.2)


class TestMarketData:
    def test_bar_ohlc_consistency(self) -> None:
        with pytest.raises(ValidationError, match="OHLC"):
            Bar(time=T0, open=1.1, high=1.09, low=1.08, close=1.085,
                tick_volume=10, spread_points=12)

    def test_tick_ask_below_bid(self) -> None:
        with pytest.raises(ValidationError):
            Tick(time=T0, bid=1.1, ask=1.09, spread_points=0)


def test_macro_unknown_fallback() -> None:
    ctx = MacroContext.unknown(T0)
    assert ctx.risk_regime == "unknown"
    assert ctx.data_stale is True


def test_model_record_requires_chronological_splits() -> None:
    day = timedelta(days=1)
    base: dict[str, Any] = {
        "version": "model-v0001", "symbol": "EURUSD", "timeframe": "M15", "features": ("rsi",),
        "train_start": T0, "train_end": T0 + 10 * day,
        "validation_start": T0 + 11 * day, "validation_end": T0 + 15 * day,
        "test_start": T0 + 16 * day, "test_end": T0 + 20 * day,
        "label_spec": {}, "metrics": {}, "costs": {}, "status": "candidate",
        "artifact_sha256": "0" * 64, "expires_at": T0 + 60 * day,
    }
    assert ModelRecord(**base).status == "candidate"
    with pytest.raises(ValidationError, match="chronological"):
        ModelRecord(**{**base, "test_start": T0 + 5 * day})


def test_risk_decision_consistency() -> None:
    with pytest.raises(ValidationError):
        RiskDecision(approved=True)
    with pytest.raises(ValidationError):
        RiskDecision(approved=False)
    assert RiskDecision(approved=False, rejections=("daily_loss_hit",)).intent is None
    assert RiskDecision(approved=True, intent=_intent(), risk_percent=0.0024).approved
