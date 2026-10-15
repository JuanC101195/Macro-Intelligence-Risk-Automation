"""Reconciliation between the loop's open tickets and the broker (ADR 0024)."""

from __future__ import annotations

from tests.fixtures.fake_demo_broker import NOW, FakeDemoBroker
from trading_system.broker.contracts import Position
from trading_system.execution.demo_executor import MAGIC
from trading_system.execution.reconciliation import reconcile


def pos(ticket: int, magic: int = MAGIC) -> Position:
    return Position(ticket=ticket, symbol="XAUUSD", side="buy", volume=0.01, open_price=4000.0,
                    stop_loss=3960.0, take_profit=4400.0, open_time=NOW, profit=0.0,
                    magic=magic, comment="x")


def test_consistent_when_everything_matches() -> None:
    r = reconcile([1, 2], [pos(1), pos(2), pos(9, magic=7)], [], MAGIC)
    assert r.consistent
    assert not r.needs_breaker


def test_closed_at_broker_with_exit_deal_is_booked_not_alarmed() -> None:
    out = FakeDemoBroker.deal(1, "sell", "out", 3960.0, "sl")
    r = reconcile([1], [], [out], MAGIC)
    assert r.closed_at_broker == (1,)
    assert r.exit_deals[1].price == 3960.0
    assert not r.needs_breaker


def test_closed_without_exit_deal_trips_the_breaker() -> None:
    r = reconcile([1], [], [], MAGIC)
    assert r.closed_at_broker == (1,)
    assert r.needs_breaker


def test_unknown_position_with_our_magic_trips_the_breaker() -> None:
    r = reconcile([], [pos(5)], [], MAGIC)
    assert r.unknown_at_broker == (5,)
    assert r.needs_breaker
