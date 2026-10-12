"""Simulated fills on M15 bars (docs/risk-policy.md §2, bid/ask table).

Bars are BID prices. A LONG exits on the bid; a SHORT exits on the ask = bid + spread.
Conservative rules:
- if a bar touches both stop and target, the STOP is assumed first;
- if the bar OPENS beyond the stop (gap), the exit is that open price, not the stop;
- take-profits fill at the target price (a limit order never fills better here).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trading_system.broker.contracts import Bar

ExitReason = Literal["stop_loss", "stop_loss_gap", "take_profit", "end_of_data"]


@dataclass(frozen=True)
class Exit:
    price: float
    reason: ExitReason


def check_exit(
    side: Literal["buy", "sell"], stop: float, target: float, bar: Bar, spread: float
) -> Exit | None:
    """Exit triggered within `bar`, or None. `spread` is in price units."""
    if side == "buy":
        if bar.open <= stop:
            return Exit(bar.open, "stop_loss_gap")
        if bar.low <= stop:
            return Exit(stop, "stop_loss")
        if bar.high >= target:
            return Exit(target, "take_profit")
        return None
    ask_open, ask_high, ask_low = bar.open + spread, bar.high + spread, bar.low + spread
    if ask_open >= stop:
        return Exit(ask_open, "stop_loss_gap")
    if ask_high >= stop:
        return Exit(stop, "stop_loss")
    if ask_low <= target:
        return Exit(target, "take_profit")
    return None


def entry_price(side: Literal["buy", "sell"], bar_open: float, spread: float,
                slippage: float) -> float:
    """Market entry at the next bar's open: buys pay the ask, both pay slippage."""
    return bar_open + spread + slippage if side == "buy" else bar_open - slippage
