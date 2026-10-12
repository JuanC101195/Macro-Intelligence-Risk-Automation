"""Regression tests for wide (daily) stops on USDXXX pairs, found in the first carry run."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.risk_fixtures import NOW, FakeQuotes, account, spec
from trading_system.broker.contracts import Tick
from trading_system.risk.circuit_breaker import FileCircuitBreaker
from trading_system.risk.contracts import ExposureSnapshot, RiskLimits
from trading_system.risk.engine import DefaultRiskEngine
from trading_system.risk.position_sizing import size_position
from trading_system.strategy.signals import Signal

LIMITS = RiskLimits(max_risk_per_trade=0.0025, max_daily_loss=0.02, max_open_positions=3,
                    max_consecutive_losses=5, max_spread_points=30, max_slippage_points=10,
                    max_trades_per_day=10)
EXPOSURE = ExposureSnapshot(open_positions=(), realized_pnl_today=0.0, unrealized_pnl=0.0,
                            consecutive_losses=0, trades_today=0, day_start_equity=100_000.0)


def _signal(entry: float, stop: float, target: float) -> Signal:
    return Signal(signal_id="s", symbol="USDJPY", timeframe="D1", bar_time=NOW, side="LONG",
                  confidence=0.5, technical_score=0, macro_regime="unknown", entry_ref=entry,
                  stop_loss=stop, take_profit=target, strategy_version="t")


def test_wide_usdjpy_stop_is_not_a_tick_value_mismatch(tmp_path: Path) -> None:
    # 4.5 yen stop (3 % of price): the broker converts the loss at 145.5, not at 150.
    engine = DefaultRiskEngine(LIMITS, FileCircuitBreaker(tmp_path / "b.json"), FakeQuotes(),
                               mode="backtest")
    jpy = spec("USDJPY", tick_value=0.001 * 100_000 / 150.0)
    tick = Tick(time=NOW, bid=150.000, ask=150.014, spread_points=14)
    d = engine.evaluate(_signal(150.014, 145.514, 180.0), account(equity=100_000.0,
                        balance=100_000.0, margin_free=100_000.0), jpy, tick, EXPOSURE)
    assert d.approved, d.rejections
    # Sized with the broker's (larger) loss at the stop: real risk stays within 0.25 %.
    assert d.intent is not None
    assert d.intent.risk_amount <= 250.0
    broker_loss = -FakeQuotes().calc_profit("USDJPY", "buy", d.intent.volume, 150.014, 145.514)
    assert broker_loss <= 250.0 + 1e-6


def test_gross_tick_value_error_still_rejected(tmp_path: Path) -> None:
    engine = DefaultRiskEngine(LIMITS, FileCircuitBreaker(tmp_path / "b.json"), FakeQuotes(),
                               mode="backtest")
    wrong = spec("USDJPY", tick_value=0.001 * 100_000)  # forgot to convert JPY -> USD (x150)
    tick = Tick(time=NOW, bid=150.000, ask=150.014, spread_points=14)
    d = engine.evaluate(_signal(150.014, 145.514, 180.0), account(equity=100_000.0,
                        balance=100_000.0, margin_free=100_000.0), wrong, tick, EXPOSURE)
    assert d.rejections == ("tick_value_mismatch",)


def test_sizing_uses_the_larger_loss_estimate() -> None:
    s = spec("USDJPY", tick_value=0.001 * 100_000 / 150.0)
    plain = size_position(100_000, 0.0025, 150.0, 145.5, s)
    conservative = size_position(100_000, 0.0025, 150.0, 145.5, s,
                                 min_loss_per_lot=4.5 * 100_000 / 145.5)
    assert conservative.volume is not None
    assert plain.volume is not None
    assert conservative.volume <= plain.volume
    assert conservative.risk_money_real <= 250.0
    assert conservative.loss_per_lot == pytest.approx(4.5 * 100_000 / 145.5)
