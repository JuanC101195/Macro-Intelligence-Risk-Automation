"""Overnight financing (swap) models for backtests (ADR 0004, ADR 0006)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from trading_system.backtest import instruments
from trading_system.macro.rates import RateHistory

BrokerSide = Literal["buy", "sell"]
Financing = Callable[[str, BrokerSide, datetime], float | None]


def make_financing(rates: RateHistory, markup: float = 1.0) -> Financing:
    """Annual net financing rate (decimal) of a position.

    - FX pairs: rate differential in favour of the position minus `markup` (percent).
    - Metals and indices: LONG pays the USD rate + markup; SHORT pays the markup and
      is credited nothing (conservative).
    """

    def financing(symbol: str, side: BrokerSide, t: datetime) -> float | None:
        if instruments.is_fx(symbol):
            d = rates.differential(symbol, t)
            if d is None:
                return None
            earned = d if side == "buy" else -d
            return (earned - markup) / 100
        if side == "sell":
            return -markup / 100
        usd = rates.rate_at("USD", t)
        return None if usd is None else -(max(usd, 0.0) + markup) / 100

    return financing
