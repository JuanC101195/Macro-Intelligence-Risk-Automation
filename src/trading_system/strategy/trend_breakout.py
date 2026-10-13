"""Trend filter EMA 50/200 + 20-bar channel breakout on gold, `trendbo-xau-v001` (ADR 0014).

- Entry at the close: close > highest high of the previous `entry_window` bars -> LONG,
  close < lowest low of the previous `entry_window` bars -> SHORT; with the trend filter
  only LONG while EMA fast > EMA slow and only SHORT while EMA fast < EMA slow.
- Initial stop `stop_atr` x ATR(14) from the entry.
- Exit mode (one per version):
  * channel: close beyond the opposite `exit_window` channel;
  * trailing: chandelier stop, extreme since the entry -/+ `trail_atr` x ATR (only tighter);
  * invalidation: the bar on which EMA fast CROSSES EMA slow against the position;
  * target: binding take-profit at `target_r` x the initial stop distance.
"Previous" never includes the current bar, so there is no look-ahead.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.domain import Side, Timeframe
from trading_system.macro.macro_context import MacroContext
from trading_system.strategy import indicators as ind
from trading_system.strategy.breakout import TARGET_FLOOR, prior_extremes
from trading_system.strategy.signals import MarketState, Signal

BrokerSide = Literal["buy", "sell"]
ExitMode = Literal["channel", "trailing", "invalidation", "target"]
EXIT_MODES: tuple[ExitMode, ...] = ("channel", "trailing", "invalidation", "target")


class TrendBreakoutParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "trendbo-xau-v001"
    timeframe: Timeframe = Timeframe.H4
    exit_mode: ExitMode = "channel"
    trend_filter: bool = True
    ema_fast: int = Field(default=50, ge=2)
    ema_slow: int = Field(default=200, ge=2)
    entry_window: int = Field(default=20, ge=2)
    exit_window: int = Field(default=10, ge=2)
    atr_period: int = 14
    stop_atr: float = Field(default=2.0, gt=0)
    trail_atr: float = Field(default=2.0, gt=0)
    target_r: float = Field(default=2.0, gt=0)
    loose_target_atr: float = Field(default=20.0, gt=0)  # non-binding target (other exits)


class _Series:
    """Precomputed per-symbol levels, indexed like the bars."""

    def __init__(self, bars: Sequence[Bar], p: TrendBreakoutParams) -> None:
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        closes = [b.close for b in bars]
        self.highs = highs
        self.lows = lows
        self.index = {b.time: i for i, b in enumerate(bars)}
        self.entry_high = prior_extremes(highs, p.entry_window, use_max=True)
        self.entry_low = prior_extremes(lows, p.entry_window, use_max=False)
        self.exit_high = prior_extremes(highs, p.exit_window, use_max=True)
        self.exit_low = prior_extremes(lows, p.exit_window, use_max=False)
        self.fast = ind.ema(closes, p.ema_fast)
        self.slow = ind.ema(closes, p.ema_slow)
        self.atr = ind.atr(highs, lows, closes, p.atr_period)

    def trend(self, i: int) -> int | None:
        """+1 up, -1 down, 0 equal, None while an EMA is not ready."""
        fast, slow = self.fast[i], self.slow[i]
        if fast is None or slow is None:
            return None
        return (fast > slow) - (fast < slow)


class TrendBreakoutStrategy:
    def __init__(self, params: TrendBreakoutParams, bars: Mapping[str, Sequence[Bar]]) -> None:
        self.params = params
        self._series = {sym: _Series(series, params) for sym, series in bars.items()}
        self._extreme: dict[tuple[str, str, datetime], tuple[int, float]] = {}  # trailing cache

    def _direction(self, s: _Series, i: int, close: float) -> Side | None:
        high, low = s.entry_high[i], s.entry_low[i]
        if high is not None and close > high:
            return Side.LONG
        if low is not None and close < low:
            return Side.SHORT
        return None

    def _hold_reason(self, s: _Series, i: int | None, side: Side | None,
                     state: MarketState) -> str | None:
        if state.has_open_position:
            return "position_open"
        if i is None or s.atr[i] is None or s.trend(i) is None:
            return "indicators_not_ready"  # same start with and without the filter
        if side is None:
            return "no_breakout"
        if self.params.trend_filter:
            wanted = 1 if side is Side.LONG else -1
            if s.trend(i) != wanted:
                return "against_trend"
        return None

    def decide(self, _snap: Any, last_bar: Bar | None, tick: Tick, spec: SymbolSpec,
               macro: MacroContext, state: MarketState, _params: Any, symbol: str
               ) -> Signal:
        """Engine decider hook (positional call); snapshot/params are unused here."""
        assert last_bar is not None
        p = self.params
        common: dict[str, Any] = {
            "signal_id": f"{p.version}-{symbol}-{last_bar.time:%Y%m%d%H}",
            "symbol": symbol, "timeframe": p.timeframe, "bar_time": last_bar.time,
            "technical_score": 0, "macro_regime": macro.risk_regime,
            "strategy_version": p.version,
        }
        s = self._series[symbol]
        i = s.index.get(last_bar.time)
        side = None if i is None else self._direction(s, i, last_bar.close)
        hold = self._hold_reason(s, i, side, state)
        atr = None if i is None else s.atr[i]
        if hold or side is None or atr is None:
            return Signal(side=Side.HOLD, confidence=0.0,
                          hold_reasons=(hold or "no_breakout",), **common)
        entry = tick.ask if side is Side.LONG else tick.bid
        sign = 1 if side is Side.LONG else -1
        risk = p.stop_atr * atr
        reach = p.target_r * risk if p.exit_mode == "target" else p.loose_target_atr * atr
        target = entry + sign * reach
        if side is Side.SHORT:
            target = max(target, entry * TARGET_FLOOR)  # keep a valid (positive) price
        return Signal(
            side=side, confidence=0.5,
            reasons=(f"close_beyond_{p.entry_window}_bar_channel",
                     "with_trend" if p.trend_filter else "no_trend_filter"),
            entry_ref=entry,
            stop_loss=round(entry - sign * risk, spec.digits),
            take_profit=round(target, spec.digits),
            **common,
        )

    def exit_check(self, symbol: str, bar: Bar, side: BrokerSide) -> bool:
        s = self._series[symbol]
        i = s.index.get(bar.time)
        if i is None:
            return False
        if self.params.exit_mode == "channel":
            low, high = s.exit_low[i], s.exit_high[i]
            if low is None or high is None:
                return False
            return bar.close < low if side == "buy" else bar.close > high
        if self.params.exit_mode == "invalidation" and i > 0:
            now, before = s.trend(i), s.trend(i - 1)
            if now is None or before is None:
                return False
            # A cross, not a state: an entry against the trend is not closed at once.
            return (now < 0 <= before) if side == "buy" else (now > 0 >= before)
        return False

    def stop_update(self, symbol: str, bar: Bar, side: BrokerSide, entry_time: datetime,
                    _entry: float, _initial: float, _current: float) -> float | None:
        """Chandelier stop for the `trailing` mode; the engine only applies tighter stops."""
        if self.params.exit_mode != "trailing":
            return None
        s = self._series[symbol]
        i = s.index.get(bar.time)
        start = s.index.get(entry_time)
        if i is None or start is None or i < start or s.atr[i] is None:
            return None
        extreme = self._running_extreme(symbol, s, side, entry_time, start, i)
        distance = self.params.trail_atr * s.atr[i]  # type: ignore[operator]
        return extreme - distance if side == "buy" else extreme + distance

    def _running_extreme(self, symbol: str, s: _Series, side: BrokerSide,
                         entry_time: datetime, start: int, i: int) -> float:
        """Highest high (buy) / lowest low (sell) from the entry bar to bar i, cached."""
        values = s.highs if side == "buy" else s.lows
        pick = max if side == "buy" else min
        last, value = self._extreme.get((symbol, side, entry_time), (start - 1, values[start]))
        if i < last:  # a new run reusing the strategy: recompute from the entry
            last, value = start - 1, values[start]
        for k in range(last + 1, i + 1):
            value = pick(value, values[k])
        self._extreme[(symbol, side, entry_time)] = (i, value)
        return value
