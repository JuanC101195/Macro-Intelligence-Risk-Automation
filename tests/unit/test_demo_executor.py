"""DemoExecutor (ADR 0024): guards, validation, idempotency, retry policy, close, sync."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.fixtures.fake_demo_broker import NOW, FakeDemoBroker
from trading_system.broker.contracts import Position
from trading_system.config import Settings
from trading_system.domain import Side, Timeframe
from trading_system.execution.demo_executor import (
    MAGIC,
    ORDER_FILLING_FOK,
    ORDER_FILLING_IOC,
    ORDER_FILLING_RETURN,
    DemoExecutor,
    demo_guard_errors,
    filling_type,
)
from trading_system.execution.order_intent import OrderIntent, make_intent_id

BAR = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def demo_settings(**over: object) -> Settings:
    base: dict[str, object] = {"trading_mode": "demo", "allow_demo_orders": True,
                               "symbols": "XAUUSD", "default_symbol": "XAUUSD"}
    base.update(over)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def intent(side: str = "buy", mode: str = "demo", volume: float = 0.01,
           sl: float | None = None, tp: float | None = None) -> OrderIntent:
    entry = 4000.30 if side == "buy" else 4000.00
    sl = sl if sl is not None else (entry - 40 if side == "buy" else entry + 40)
    tp = tp if tp is not None else (entry + 400 if side == "buy" else entry - 400)
    return OrderIntent(
        intent_id=make_intent_id("trendbo-xau-h4-channel", "XAUUSD", Timeframe.H4, BAR,
                                 Side.LONG if side == "buy" else Side.SHORT),
        signal_id="s1", signal_bar_time=BAR, symbol="XAUUSD", side=side,  # type: ignore[arg-type]
        entry_price=entry, stop_loss=sl, take_profit=tp, volume=volume, risk_amount=40.0,
        strategy_version="trendbo-xau-h4-channel", mode=mode,  # type: ignore[arg-type]
        reason="test")


def make(broker: FakeDemoBroker | None = None, **settings: object
         ) -> tuple[DemoExecutor, FakeDemoBroker]:
    b = broker or FakeDemoBroker()
    return DemoExecutor(b, demo_settings(**settings), clock=lambda: NOW), b


# --- guards ---------------------------------------------------------------------------------

def test_guard_lists_every_problem() -> None:
    paper = Settings(_env_file=None, symbols="XAUUSD", default_symbol="XAUUSD")  # type: ignore[call-arg]
    real = FakeDemoBroker(trade_mode="real").account_info()
    errors = demo_guard_errors(paper, real)
    assert any("TRADING_MODE" in e for e in errors)
    assert any("ALLOW_DEMO_ORDERS" in e for e in errors)
    assert any("real" in e for e in errors)
    assert demo_guard_errors(demo_settings(), FakeDemoBroker().account_info()) == []


def test_paper_settings_never_reach_the_terminal() -> None:
    b = FakeDemoBroker()
    ex = DemoExecutor(b, Settings(_env_file=None, symbols="XAUUSD",  # type: ignore[call-arg]
                                  default_symbol="XAUUSD"), clock=lambda: NOW)
    r = ex.submit(intent())
    assert r.status == "rejected"
    assert "TRADING_MODE" in r.message
    assert b.terminal_calls == 0
    assert b.terminal.requests == []


def test_real_account_is_refused_before_the_terminal() -> None:
    ex, b = make(FakeDemoBroker(trade_mode="real"))
    r = ex.submit(intent())
    assert r.status == "rejected"
    assert "not demo" in r.message
    assert b.terminal_calls == 0


def test_non_demo_intent_is_rejected() -> None:
    ex, b = make()
    r = ex.submit(intent(mode="paper"))
    assert r.status == "rejected"
    assert "mode paper" in r.message
    assert b.terminal.requests == []


@pytest.mark.parametrize(("volume", "fragment"), [(0.015, "multiple"), (200.0, "outside")])
def test_invalid_volume_is_rejected_without_sending(volume: float, fragment: str) -> None:
    ex, b = make()
    r = ex.submit(intent(volume=volume))
    assert r.status == "rejected"
    assert fragment in r.message
    assert b.terminal.requests == []


def test_stop_without_bracket_cannot_even_be_built() -> None:
    with pytest.raises(ValueError):
        intent(sl=4001.0)  # a buy stop above the entry


@pytest.mark.parametrize(("bid", "fragment"), [(3959.00, "stop"), (4401.00, "take-profit")])
def test_price_moved_past_stop_or_target_is_rejected(bid: float, fragment: str) -> None:
    ex, b = make()
    b.bid, b.ask = bid, bid + 0.30  # the market moved after the intent was built
    r = ex.submit(intent())
    assert r.status == "rejected"
    assert fragment in r.message
    assert b.terminal.requests == []


# --- happy path and request content ---------------------------------------------------------

def test_buy_is_filled_with_magic_comment_and_stops() -> None:
    ex, b = make()
    b.terminal.fill_price = 4000.50
    it = intent()
    r = ex.submit(it)
    assert r.status == "filled"
    assert r.broker_ticket == 1001
    assert r.slippage_points == pytest.approx(20.0)  # 0.20 USD worse than expected
    req = b.terminal.requests[0]
    assert req["magic"] == MAGIC
    assert req["comment"] == it.intent_id
    assert req["sl"] == it.stop_loss
    assert req["tp"] == it.take_profit
    assert req["type"] == 0
    assert req["price"] == 4000.30
    assert req["type_filling"] == ORDER_FILLING_FOK


def test_sell_slippage_sign() -> None:
    ex, b = make()
    b.terminal.fill_price = 3999.90  # sold 0.10 lower than the bid: adverse
    r = ex.submit(intent(side="sell"))
    assert r.status == "filled"
    assert r.slippage_points == pytest.approx(10.0)
    assert b.terminal.requests[0]["type"] == 1


def test_filling_type_follows_symbol_flags() -> None:
    assert filling_type(1) == ORDER_FILLING_FOK
    assert filling_type(2) == ORDER_FILLING_IOC
    assert filling_type(3) == ORDER_FILLING_FOK
    assert filling_type(0) == ORDER_FILLING_RETURN


# --- idempotency ----------------------------------------------------------------------------

def test_open_position_with_the_same_intent_is_a_duplicate() -> None:
    ex, b = make()
    assert ex.submit(intent()).status == "filled"
    again = ex.submit(intent())
    assert again.status == "duplicate"
    assert again.broker_ticket == 1001
    assert len(b.terminal.requests) == 1


def test_closed_position_found_in_history_is_a_duplicate() -> None:
    ex, b = make()
    it = intent()
    b.history.append(FakeDemoBroker.deal(777, "buy", "in", 4000.3, it.intent_id))
    r = ex.submit(it)
    assert r.status == "duplicate"
    assert r.broker_ticket == 777
    assert b.terminal.requests == []


def test_foreign_magic_is_not_mistaken_for_ours() -> None:
    ex, b = make()
    it = intent()
    b.history.append(FakeDemoBroker.deal(5, "buy", "in", 4000.3, it.intent_id, magic=1))
    assert ex.submit(it).status == "filled"


# --- retry policy ---------------------------------------------------------------------------

def test_requote_is_rejected_without_retry() -> None:
    ex, b = make()
    b.terminal.script = [10004]
    r = ex.submit(intent())
    assert r.status == "rejected"
    assert "10004" in r.message
    assert len(b.terminal.requests) == 1


def test_lost_answer_is_confirmed_by_state_without_resending() -> None:
    ex, b = make()
    b.terminal.script = ["ghost"]
    r = ex.submit(intent())
    assert r.status == "filled"
    assert "confirmed by state" in r.message
    assert len(b.terminal.requests) == 1
    assert len(b.open_positions) == 1


def test_transient_then_done_retries_once() -> None:
    ex, b = make()
    b.terminal.script = [10031, 10009]
    assert ex.submit(intent()).status == "filled"
    assert len(b.terminal.requests) == 2
    assert len(b.open_positions) == 1


def test_transient_twice_is_unknown_after_one_retry() -> None:
    ex, b = make()
    b.terminal.script = [None, 10012]
    r = ex.submit(intent())
    assert r.status == "unknown"
    assert len(b.terminal.requests) == 2
    assert b.open_positions == []


# --- close, stop, sync ----------------------------------------------------------------------

def test_close_sends_the_opposite_deal_for_that_position() -> None:
    ex, b = make()
    ticket = ex.submit(intent()).broker_ticket
    assert ticket is not None
    r = ex.close(ticket, "signal_exit")
    req = b.terminal.requests[-1]
    assert r.status == "filled"
    assert req["position"] == ticket
    assert req["type"] == 1
    assert req["price"] == b.bid
    assert req["comment"] == "x:signal_exit"
    assert b.open_positions == []


def test_close_of_a_position_already_gone_is_a_duplicate() -> None:
    ex, b = make()
    r = ex.close(4242, "signal_exit")
    assert r.status == "duplicate"
    assert b.terminal.requests == []


def test_close_with_lost_answer_is_confirmed_by_state() -> None:
    ex, b = make()
    ticket = ex.submit(intent()).broker_ticket
    assert ticket is not None
    b.terminal.script = ["ghost"]
    assert ex.close(ticket, "signal_exit").status == "filled"


def test_modify_stop_uses_sltp_action() -> None:
    ex, b = make()
    ticket = ex.submit(intent()).broker_ticket
    assert ticket is not None
    r = ex.modify_stop(ticket, 3990.0)
    assert r.status == "filled"
    assert b.terminal.requests[-1]["action"] == 6
    assert b.open_positions[0].stop_loss == 3990.0


def test_sync_only_returns_our_positions() -> None:
    ex, b = make()
    b.open_positions.append(Position(ticket=1, symbol="XAUUSD", side="buy", volume=0.01,
                                     open_price=4000.0, stop_loss=None, take_profit=None,
                                     open_time=NOW, profit=0.0, magic=1, comment="manual"))
    ex.submit(intent())
    assert [p.magic for p in ex.sync()] == [MAGIC]
