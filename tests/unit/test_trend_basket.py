from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trading_system.backtest.engine import ClosedTrade
from trading_system.backtest.trend_suite import BASKET, TIMEFRAMES, _per_symbol, weekly_stats
from trading_system.domain import Timeframe

MONDAY = datetime(2026, 1, 5, 10, tzinfo=UTC)


def _trade(symbol: str, day: int, pnl: float) -> ClosedTrade:
    t = MONDAY + timedelta(days=day)
    return ClosedTrade(symbol=symbol, side="buy", signal_time=t, entry_time=t, entry_price=1.0,
                       exit_time=t + timedelta(hours=4), exit_price=1.1, volume=0.01,
                       risk_amount=10.0, pnl=pnl, exit_reason="signal_exit")


def test_basket_is_the_adr_0006_universe_and_h1_is_allowed() -> None:
    assert len(BASKET) == 11
    assert "USTEC" not in BASKET
    assert Timeframe.H1 in TIMEFRAMES


def test_weekly_stats_counts_weeks_and_results() -> None:
    trades = [_trade("XAUUSD", 0, 100.0), _trade("EURUSD", 1, -50.0), _trade("XAUUSD", 14, 30.0)]
    stats = weekly_stats(trades, capital=10_000.0)
    # first entry Monday week 1, last exit Monday week 3 -> 2 weeks span
    assert stats["trades_per_week_mean"] == 1.5
    assert stats["worst_week_pct"] == 0.3
    assert stats["worst_month_pct"] == 0.8
    assert stats["trades_per_week_median_active"] == 1.5


def test_weekly_stats_empty() -> None:
    assert weekly_stats([], capital=10_000.0) == {"weeks": 0}


def test_per_symbol_profit_factor() -> None:
    rows = _per_symbol([_trade("XAUUSD", 0, 30.0), _trade("XAUUSD", 1, -10.0),
                        _trade("EURUSD", 2, -5.0)])
    assert rows["XAUUSD"] == {"trades": 2, "net": 20.0, "gross_win": 30.0, "gross_loss": 10.0,
                              "pf": 3.0}
    assert rows["EURUSD"]["pf"] == 0.0
