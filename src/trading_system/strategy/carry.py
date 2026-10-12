"""FX carry strategy `carry-v001` (ADR 0004).

At each rebalance (first D1 bar of the month, or of the week in the weekly variant):
- differential d = rate(base) - rate(quote) per pair, with point-in-time FRED rates;
- candidates |d| >= threshold; keep the `max_positions` largest |d|;
- LONG if d > 0, SHORT if d < 0; stop 3 x ATR(20), take-profit 20 x ATR (non-binding);
- an open position is closed at a rebalance if it is no longer selected or flips side.
Financing (swap) of a position: (rate_long - rate_short - markup) per year.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.domain import Side, Timeframe
from trading_system.macro.macro_context import MacroContext
from trading_system.macro.rates import RateHistory
from trading_system.strategy import indicators as ind
from trading_system.strategy.signals import MarketState, Signal

BrokerSide = Literal["buy", "sell"]
DAY = timedelta(days=1)


class CarryParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "carry-v001"
    threshold: float = Field(default=0.50, ge=0)  # percentage points
    max_positions: int = Field(default=3, ge=1, le=3)  # risk-policy ceiling
    atr_period: int = 20
    stop_atr: float = Field(default=3.0, gt=0)
    target_atr: float = Field(default=20.0, gt=0)
    rebalance: Literal["monthly", "weekly"] = "monthly"
    swap_markup: float = Field(default=1.0, ge=0)  # percent per year, always paid


def _period(t: datetime, rebalance: str) -> tuple[int, int]:
    if rebalance == "weekly":
        year, week, _ = t.isocalendar()
        return year, week
    return t.year, t.month


class CarryStrategy:
    def __init__(self, params: CarryParams, rates: RateHistory,
                 bars: Mapping[str, Sequence[Bar]]) -> None:
        self.params = params
        self.rates = rates
        self._atr: dict[tuple[str, datetime], float] = {}
        self._rebalance_bars: set[tuple[str, datetime]] = set()
        for sym, series in bars.items():
            highs = [b.high for b in series]
            lows = [b.low for b in series]
            closes = [b.close for b in series]
            atr = ind.atr(highs, lows, closes, params.atr_period)
            previous: tuple[int, int] | None = None
            for bar, value in zip(series, atr, strict=True):
                if value is not None:
                    self._atr[(sym, bar.time)] = value
                period = _period(bar.time, params.rebalance)
                if period != previous:
                    self._rebalance_bars.add((sym, bar.time))
                previous = period
        self._symbols = tuple(sorted(bars))

    # --- selection --------------------------------------------------------------------

    def targets(self, t: datetime) -> dict[str, Side]:
        diffs = []
        for sym in self._symbols:
            d = self.rates.differential(sym, t)
            if d is not None and abs(d) >= self.params.threshold:
                diffs.append((abs(d), sym, d))
        diffs.sort(key=lambda x: (-x[0], x[1]))  # deterministic tie-break by symbol
        return {sym: (Side.LONG if d > 0 else Side.SHORT)
                for _, sym, d in diffs[:self.params.max_positions]}

    def is_rebalance(self, sym: str, bar: Bar) -> bool:
        return (sym, bar.time) in self._rebalance_bars

    # --- hooks for the backtest engine ------------------------------------------------

    def decide(self, snap: Any, last_bar: Bar | None, tick: Tick, spec: SymbolSpec,
               macro: MacroContext, state: MarketState, p: Any, symbol: str) -> Signal:
        assert last_bar is not None
        common: dict[str, Any] = {
            "signal_id": f"{self.params.version}-{symbol}-{last_bar.time:%Y%m%d}",
            "symbol": symbol, "timeframe": Timeframe.D1, "bar_time": last_bar.time,
            "technical_score": 0, "macro_regime": macro.risk_regime,
            "strategy_version": self.params.version,
        }
        hold = self._hold_reason(symbol, last_bar, state)
        if hold:
            return Signal(side=Side.HOLD, confidence=0.0, hold_reasons=(hold,), **common)
        side = self.targets(last_bar.time + DAY)[symbol]
        atr = self._atr[(symbol, last_bar.time)]
        entry = tick.ask if side is Side.LONG else tick.bid
        sign = 1 if side is Side.LONG else -1
        d = self.rates.differential(symbol, last_bar.time + DAY)
        return Signal(
            side=side, confidence=0.5,
            reasons=(f"carry_differential={d:+.2f}",),
            entry_ref=entry,
            stop_loss=round(entry - sign * self.params.stop_atr * atr, spec.digits),
            take_profit=round(entry + sign * self.params.target_atr * atr, spec.digits),
            **common,
        )

    def _hold_reason(self, symbol: str, bar: Bar, state: MarketState) -> str | None:
        if not self.is_rebalance(symbol, bar):
            return "not_rebalance_bar"
        if symbol not in self.targets(bar.time + DAY):
            return "not_selected"
        if state.has_open_position:
            return "position_open"
        if (symbol, bar.time) not in self._atr:
            return "indicators_not_ready"
        return None

    def exit_check(self, symbol: str, bar: Bar, side: BrokerSide) -> bool:
        if not self.is_rebalance(symbol, bar):
            return False
        target = self.targets(bar.time + DAY).get(symbol)
        wanted = None if target is None else ("buy" if target is Side.LONG else "sell")
        return wanted != side

    def financing(self, symbol: str, side: BrokerSide, t: datetime) -> float | None:
        d = self.rates.differential(symbol, t)
        if d is None:
            return None
        earned = d if side == "buy" else -d
        return (earned - self.params.swap_markup) / 100
