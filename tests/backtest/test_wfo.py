"""Walk-forward optimization (ADR 0012): choices use only closed past trades."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from trading_system.backtest import wfo
from trading_system.backtest.engine import ClosedTrade
from trading_system.broker.contracts import Bar
from trading_system.domain import Side
from trading_system.strategy.signals import MarketState, Signal

W1 = (datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 7, 1, tzinfo=UTC))
W2 = (datetime(2020, 7, 1, tzinfo=UTC), datetime(2021, 1, 1, tzinfo=UTC))


def trade(entry: datetime, r: float, days: int = 2) -> ClosedTrade:
    return ClosedTrade(symbol="XAUUSD", side="buy", signal_time=entry, entry_time=entry,
                       entry_price=100.0, exit_time=entry + timedelta(days=days),
                       exit_price=101.0, volume=0.01, risk_amount=10.0, pnl=10.0 * r,
                       exit_reason="take_profit")


def series(start: datetime, n: int, r: float, step_days: int = 5) -> list[ClosedTrade]:
    return [trade(start + timedelta(days=step_days * i), r) for i in range(n)]


def test_choice_uses_only_trades_closed_before_the_window() -> None:
    early = datetime(2019, 1, 1, tzinfo=UTC)
    good_past = series(early, 30, 0.5)  # all closed in 2019
    # Great, but only AFTER W1 starts: must not influence the W1 choice.
    future = series(early, 30, -0.2) + series(W1[0], 40, 3.0)
    windows = wfo.schedule({"a": good_past, "b": future}, [W1, W2], 12, "expectancy_r", 30)
    assert windows[0].choice == "a"
    assert windows[0].scores["b"][0] == 30  # the in-window trades were not counted


def test_no_choice_without_enough_trades_or_edge() -> None:
    early = datetime(2019, 6, 1, tzinfo=UTC)
    few = series(early, 10, 1.0)
    losing = series(early, 40, -0.1, step_days=3)
    [w] = wfo.schedule({"few": few, "losing": losing}, [W1], 12, "expectancy_r", 30)
    assert w.choice is None


def test_ties_go_to_the_first_variant() -> None:
    early = datetime(2019, 1, 1, tzinfo=UTC)
    same = series(early, 30, 0.4)
    [w] = wfo.schedule({"first": same, "second": list(same)}, [W1], 12, "expectancy_r", 30)
    assert w.choice == "first"


def _decider(label: str) -> Any:
    def decide(snap: Any, bar: Bar | None, *rest: Any) -> Signal:
        assert bar is not None
        return Signal(signal_id=label, symbol="XAUUSD", timeframe="M5", bar_time=bar.time,
                      side=Side.LONG, confidence=0.5, technical_score=0, macro_regime="mixed",
                      entry_ref=100.0, stop_loss=99.0, take_profit=102.0,
                      strategy_version=label)
    return decide


def test_switching_delegates_per_window_and_holds_outside() -> None:
    windows = [wfo.Window(*W1, choice="a", scores={}), wfo.Window(*W2, choice=None, scores={})]
    sw = wfo.Switching({"a": _decider("a"), "b": _decider("b")}, windows)
    state = MarketState(has_open_position=False, risk_blocked=False)

    def at(t: datetime) -> Signal:
        bar = Bar(time=t, open=1, high=1, low=1, close=1, tick_volume=1, spread_points=0)
        return sw(None, bar, None, None, None, state, None, "XAUUSD")

    assert at(datetime(2020, 3, 1, tzinfo=UTC)).strategy_version == "a"
    assert at(datetime(2020, 9, 1, tzinfo=UTC)).hold_reasons == ("wfo_no_variant",)
    assert at(datetime(2019, 9, 1, tzinfo=UTC)).side is Side.HOLD  # before the first window
    assert at(datetime(2021, 2, 1, tzinfo=UTC)).side is Side.HOLD  # after the last window
