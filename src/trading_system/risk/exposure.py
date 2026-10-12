"""Exposure helpers: trading day, currency legs, open risk to stop (docs/risk-policy.md)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from trading_system.broker.contracts import Position

NEW_YORK = ZoneInfo("America/New_York")
ROLLOVER = time(17, 0)  # FX trading day starts at 17:00 New York time (ADR 0001 #13)

Side = Literal["buy", "sell"]


class ProfitCalculator(Protocol):
    """Subset of MarketDataSource the risk engine needs (MT5 order_calc_*)."""

    def calc_margin(self, symbol: str, side: Side, volume: float, price: float) -> float: ...
    def calc_profit(
        self, symbol: str, side: Side, volume: float, price_open: float, price_close: float
    ) -> float: ...


def trading_day_start(now: datetime) -> datetime:
    """Start of the FX trading day containing `now` (17:00 New York, DST-aware), in now's tz."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(NEW_YORK)
    day = local.date() if local.time() >= ROLLOVER else local.date() - timedelta(days=1)
    start = datetime.combine(day, ROLLOVER, tzinfo=NEW_YORK)
    return start.astimezone(now.tzinfo)


def currency_legs(symbol: str, side: Side) -> dict[str, int]:
    """LONG EURUSD = long EUR (+1), short USD (-1). Six-letter FX symbols only."""
    if len(symbol) != 6 or not symbol.isalpha():
        raise ValueError(f"not a six-letter FX symbol: {symbol}")
    sign = 1 if side == "buy" else -1
    return {symbol[:3].upper(): sign, symbol[3:].upper(): -sign}


def risk_to_stop(position: Position, quotes: ProfitCalculator) -> float | None:
    """Money lost if the position hits its stop (>= 0). None if it has no stop."""
    if position.stop_loss is None:
        return None
    pnl_at_stop = quotes.calc_profit(
        position.symbol, position.side, position.volume, position.open_price, position.stop_loss
    )
    return max(0.0, -pnl_at_stop)
