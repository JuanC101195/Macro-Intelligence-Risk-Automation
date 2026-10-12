"""Channel breakout (Donchian / "Turtle"-style) trend following `breakout-v001` (ADR 0006).

- Entry at the close: close > highest high of the previous `entry_window` bars -> LONG;
  close < lowest low of the previous `entry_window` bars -> SHORT.
- Exit at the close: LONG when close < lowest low of the previous `exit_window` bars;
  SHORT when close > highest high of the previous `exit_window` bars.
- Stop 2 x ATR(20) from the entry; take-profit 20 x ATR (contractual, non-binding).
"Previous" never includes the current bar, so there is no look-ahead.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.domain import Side, Timeframe
from trading_system.macro.macro_context import MacroContext
from trading_system.strategy import indicators as ind
from trading_system.strategy.signals import MarketState, Signal

BrokerSide = Literal["buy", "sell"]
TARGET_FLOOR = 0.10  # short targets never below 10 % of the entry (ADR 0006 addendum)


class BreakoutParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "breakout-v001"
    entry_window: int = Field(default=55, ge=2)
    exit_window: int = Field(default=20, ge=2)
    atr_period: int = 20
    stop_atr: float = Field(default=2.0, gt=0)
    target_atr: float = Field(default=20.0, gt=0)


@dataclass(frozen=True)
class _Levels:
    entry_high: float | None
    entry_low: float | None
    exit_high: float | None
    exit_low: float | None
    atr: float | None


def _prior_extremes(values: Sequence[float], window: int, use_max: bool) -> list[float | None]:
    """Max/min of the `window` values BEFORE each index (current value excluded)."""
    out: list[float | None] = [None] * len(values)
    pick = max if use_max else min
    for i in range(window, len(values)):
        out[i] = pick(values[i - window:i])
    return out


class BreakoutStrategy:
    def __init__(self, params: BreakoutParams, bars: Mapping[str, Sequence[Bar]]) -> None:
        self.params = params
        self._levels: dict[tuple[str, datetime], _Levels] = {}
        for sym, series in bars.items():
            highs = [b.high for b in series]
            lows = [b.low for b in series]
            closes = [b.close for b in series]
            eh = _prior_extremes(highs, params.entry_window, use_max=True)
            el = _prior_extremes(lows, params.entry_window, use_max=False)
            xh = _prior_extremes(highs, params.exit_window, use_max=True)
            xl = _prior_extremes(lows, params.exit_window, use_max=False)
            atr = ind.atr(highs, lows, closes, params.atr_period)
            for i, bar in enumerate(series):
                self._levels[(sym, bar.time)] = _Levels(eh[i], el[i], xh[i], xl[i], atr[i])

    def _direction(self, symbol: str, bar: Bar) -> Side | None:
        lv = self._levels.get((symbol, bar.time))
        if lv is None or lv.entry_high is None or lv.entry_low is None:
            return None
        if bar.close > lv.entry_high:
            return Side.LONG
        if bar.close < lv.entry_low:
            return Side.SHORT
        return None

    def decide(self, _snap: Any, last_bar: Bar | None, tick: Tick, spec: SymbolSpec,
               macro: MacroContext, state: MarketState, _params: Any, symbol: str
               ) -> Signal:
        """Engine decider hook (positional call); snapshot/params are unused here."""
        assert last_bar is not None
        common: dict[str, Any] = {
            "signal_id": f"{self.params.version}-{symbol}-{last_bar.time:%Y%m%d}",
            "symbol": symbol, "timeframe": Timeframe.D1, "bar_time": last_bar.time,
            "technical_score": 0, "macro_regime": macro.risk_regime,
            "strategy_version": self.params.version,
        }
        side = self._direction(symbol, last_bar)
        lv = self._levels.get((symbol, last_bar.time))
        hold = None
        if state.has_open_position:
            hold = "position_open"
        elif side is None:
            hold = "no_breakout"
        elif lv is None or lv.atr is None:
            hold = "indicators_not_ready"
        if hold or side is None or lv is None or lv.atr is None:
            return Signal(side=Side.HOLD, confidence=0.0, hold_reasons=(hold or "no_breakout",),
                          **common)
        entry = tick.ask if side is Side.LONG else tick.bid
        sign = 1 if side is Side.LONG else -1
        target = entry + sign * self.params.target_atr * lv.atr
        if side is Side.SHORT:
            # The contractual target is non-binding; keep it a valid (positive) price.
            target = max(target, entry * TARGET_FLOOR)
        return Signal(
            side=side, confidence=0.5,
            reasons=(f"close_beyond_{self.params.entry_window}d_channel",),
            entry_ref=entry,
            stop_loss=round(entry - sign * self.params.stop_atr * lv.atr, spec.digits),
            take_profit=round(target, spec.digits),
            **common,
        )

    def exit_check(self, symbol: str, bar: Bar, side: BrokerSide) -> bool:
        lv = self._levels.get((symbol, bar.time))
        if lv is None or lv.exit_high is None or lv.exit_low is None:
            return False
        if side == "buy":
            return bar.close < lv.exit_low
        return bar.close > lv.exit_high
