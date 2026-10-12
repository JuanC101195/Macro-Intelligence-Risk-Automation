"""Position sizing (docs/risk-policy.md §2).

    risk_money    = equity x risk_fraction
    ticks_to_stop = |entry - stop| / tick_size
    loss_per_lot  = ticks_to_stop x tick_value      (tick_value in account currency)
    volume        = floor(risk_money / loss_per_lot / volume_step) x volume_step

Volume is ALWAYS rounded down. Below the broker minimum the trade is rejected:
rounding up would risk more than allowed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from trading_system.broker.contracts import SymbolSpec

# Guards float noise like 0.12 / 0.01 = 11.999999999 without ever rounding up materially.
_EPS = 1e-9


@dataclass(frozen=True)
class SizingResult:
    volume: float | None  # None = rejected
    risk_money_allowed: float
    risk_money_real: float  # loss at the stop with the final volume
    loss_per_lot: float
    rejection: str | None = None


def _decimals(step: float) -> int:
    text = f"{step:.10f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def size_position(
    equity: float, risk_fraction: float, entry: float, stop: float, spec: SymbolSpec
) -> SizingResult:
    if equity <= 0 or risk_fraction <= 0:
        return SizingResult(None, 0.0, 0.0, 0.0, "non_positive_equity_or_risk")
    risk_money = equity * risk_fraction
    distance = abs(entry - stop)
    if distance <= 0:
        return SizingResult(None, risk_money, 0.0, 0.0, "zero_stop_distance")

    loss_per_lot = distance / spec.tick_size * spec.tick_value
    raw_volume = risk_money / loss_per_lot
    steps = math.floor(raw_volume / spec.volume_step + _EPS)
    volume = round(steps * spec.volume_step, _decimals(spec.volume_step))

    if volume < spec.volume_min:
        return SizingResult(None, risk_money, 0.0, loss_per_lot, "volume_below_min")
    volume = min(volume, spec.volume_max)
    real = volume * loss_per_lot
    if real > risk_money * (1 + 1e-6):  # impossible by construction; defensive
        return SizingResult(None, risk_money, real, loss_per_lot, "sizing_exceeds_risk")
    return SizingResult(volume, risk_money, real, loss_per_lot)
