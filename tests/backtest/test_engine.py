"""Backtest engine mechanics with a scripted decider and hand-computed prices."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from trading_system.backtest.engine import Backtest, BacktestConfig
from trading_system.broker.contracts import Bar
from trading_system.domain import Side
from trading_system.risk.contracts import RiskLimits
from trading_system.strategy.signals import Signal

T0 = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)  # a Wednesday, mid-session
M15 = timedelta(minutes=15)
LIMITS = RiskLimits(max_risk_per_trade=0.0025, max_daily_loss=0.02, max_open_positions=1,
                    max_consecutive_losses=3, max_spread_points=30, max_slippage_points=10,
                    max_trades_per_day=5)


def bar(i: int, o: float, h: float, lo: float, c: float, t0: datetime = T0) -> Bar:
    return Bar(time=t0 + M15 * i, open=o, high=h, low=lo, close=c, tick_volume=1, spread_points=0)


def four_bars(b3: tuple[float, ...], b4: tuple[float, ...]) -> list[Bar]:
    """Three flat bars, then bars 3 and 4 as (open, high, low, close)."""
    return flat(3) + [bar(3, *b3), bar(4, *b4)]


def flat(n: int, price: float = 1.1000) -> list[Bar]:
    return [bar(i, price, price + 0.0005, price - 0.0005, price) for i in range(n)]


def scripted(plan: dict[tuple[str, datetime], tuple[str, float, float, float]]) -> Any:
    """decider that trades only where `plan` says: (side, entry_ref, stop, target)."""

    def decider(snap: Any, last_bar: Bar | None, tick: Any, spec: Any, macro: Any, state: Any,
                p: Any, symbol: str) -> Signal:
        assert last_bar is not None
        common = {"signal_id": f"{symbol}-{last_bar.time:%H%M}", "symbol": symbol,
                  "timeframe": "M15", "bar_time": last_bar.time, "technical_score": 100,
                  "macro_regime": "mixed", "strategy_version": "test-v1"}
        key = (symbol, last_bar.time)
        if key not in plan or state.has_open_position:
            return Signal(side=Side.HOLD, confidence=0.0, hold_reasons=("no_setup",), **common)
        side, entry, stop, target = plan[key]
        return Signal(side=Side(side), confidence=0.6, entry_ref=entry, stop_loss=stop,
                      take_profit=target, **common)

    return decider


def run(bars: dict[str, list[Bar]], plan: dict[Any, Any], **cfg: Any) -> Any:
    config = BacktestConfig(symbols=tuple(sorted(bars)), start=T0,
                            end=T0 + timedelta(days=30), limits=LIMITS, **cfg)
    return Backtest(config, bars, decider=scripted(plan)).run()


def test_long_take_profit_with_costs_by_hand() -> None:
    bars = four_bars((1.1001, 1.1010, 1.0995, 1.1005), (1.1005, 1.1045, 1.1000, 1.1040))
    # Signal at the close of bar 2 (ask = 1.1000 + 12 points).
    r = run({"EURUSD": bars}, {("EURUSD", bars[2].time): ("LONG", 1.10012, 1.0980, 1.1040)})
    [t] = r.trades
    # Risk 25 USD / (212 ticks x 1 USD) = 0.1179 -> 0.11 lots (rounded down)
    assert t.volume == 0.11
    assert t.entry_time == bars[3].time  # next bar open, not the signal bar's close
    assert t.entry_price == pytest.approx(1.1001 + 0.00012 + 0.00002)  # open + spread + slippage
    assert t.exit_reason == "take_profit"
    assert t.exit_price == 1.1040
    assert t.pnl == pytest.approx((1.1040 - 1.10024) * 0.11 * 100_000, abs=0.01)
    assert r.final_equity == pytest.approx(10_000 + t.pnl)


def test_stop_assumed_first_when_bar_touches_both() -> None:
    bars = four_bars((1.1001, 1.1010, 1.0995, 1.1005), (1.1005, 1.1045, 1.0975, 1.1000))
    r = run({"EURUSD": bars}, {("EURUSD", bars[2].time): ("LONG", 1.10012, 1.0980, 1.1040)})
    [t] = r.trades
    assert t.exit_reason == "stop_loss"
    assert t.exit_price == pytest.approx(1.0980 - 0.00002)  # stops slip
    assert t.pnl < 0


def test_long_gap_through_stop_exits_at_open() -> None:
    bars = four_bars((1.1001, 1.1010, 1.0995, 1.1005), (1.0960, 1.0965, 1.0950, 1.0955))
    r = run({"EURUSD": bars}, {("EURUSD", bars[2].time): ("LONG", 1.10012, 1.0980, 1.1040)})
    [t] = r.trades
    assert t.exit_reason == "stop_loss_gap"
    assert t.exit_price == pytest.approx(1.0960 - 0.00002)
    assert t.r_multiple < -1  # gaps lose more than 1R: the backtest must show it


def test_short_exits_on_the_ask() -> None:
    # Target 1.0960 is reached only when the ASK (low + 12 points) gets there.
    bars = four_bars((1.1001, 1.1005, 1.0990, 1.0995), (1.0995, 1.0996, 1.0947, 1.0950))
    r = run({"EURUSD": bars}, {("EURUSD", bars[2].time): ("SHORT", 1.1000, 1.1020, 1.0960)})
    [t] = r.trades
    assert t.side == "sell"
    assert t.entry_price == pytest.approx(1.1001 - 0.00002)  # sells at the bid, minus slippage
    assert t.exit_reason == "take_profit"
    assert t.pnl == pytest.approx((1.10008 - 1.0960) * 0.12 * 100_000, abs=0.01)


def test_short_target_not_hit_if_only_the_bid_touches_it() -> None:
    bars = four_bars((1.1001, 1.1005, 1.0990, 1.0995), (1.0995, 1.0996, 1.0959, 1.0970))
    r = run({"EURUSD": bars}, {("EURUSD", bars[2].time): ("SHORT", 1.1000, 1.1020, 1.0960)})
    [t] = r.trades
    assert t.exit_reason == "end_of_data"  # bid low 1.0959 < 1.0960 but ask low 1.09602 > target


def test_fill_cancelled_across_data_gap() -> None:
    bars = flat(3) + [bar(5, 1.1001, 1.1010, 1.0995, 1.1005)]  # bar 3 and 4 missing
    r = run({"EURUSD": bars}, {("EURUSD", bars[2].time): ("LONG", 1.10012, 1.0980, 1.1040)})
    assert r.trades == []
    assert r.cancelled_fills == 1


def test_portfolio_limit_counts_pending_orders() -> None:
    eur, gbp = flat(6), flat(6, 1.2700)
    plan = {("EURUSD", eur[2].time): ("LONG", 1.10012, 1.0980, 1.1040),
            ("GBPUSD", gbp[2].time): ("LONG", 1.27016, 1.2680, 1.2740)}
    r = run({"EURUSD": eur, "GBPUSD": gbp}, plan)
    assert [t.symbol for t in r.trades] == ["EURUSD"]
    assert r.rejections["max_open_positions"] == 1


def test_reproducible() -> None:
    bars = four_bars((1.1001, 1.1010, 1.0995, 1.1005), (1.1005, 1.1045, 1.1000, 1.1040))
    plan = {("EURUSD", bars[2].time): ("LONG", 1.10012, 1.0980, 1.1040)}
    first, second = run({"EURUSD": bars}, plan), run({"EURUSD": bars}, plan)
    assert first.digest() == second.digest()


def test_breaker_reset_by_simulated_operator_next_trading_day() -> None:
    config = BacktestConfig(symbols=("EURUSD",), start=T0, end=T0 + timedelta(days=3),
                            limits=LIMITS)
    bt = Backtest(config, {"EURUSD": flat(3)})
    bt._roll_day(T0)
    bt.breaker.trip("max_consecutive_losses", source="risk")
    bt.book.consecutive_losses = 3
    bt._roll_day(T0 + timedelta(hours=2))  # same trading day: stays open
    assert bt.breaker.is_open()
    bt._roll_day(T0 + timedelta(days=1))  # next 17:00 New York passed
    assert not bt.breaker.is_open()
    assert bt.book.consecutive_losses == 0
    assert bt.breaker.resets == [("backtest-operator", "new trading day")]
