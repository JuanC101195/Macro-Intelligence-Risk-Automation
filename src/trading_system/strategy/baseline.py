"""Deterministic baseline strategy `baseline-v001` (CLAUDE.md §8, implementation plan Phase 4).

Rules (all thresholds in BaselineParams, fixed before any backtest — ADR 0002):

LONG  : EMA50 > EMA200, close > EMA50, RSI dipped below 40 within the last 5 bars
        and is now back above 40 and rising, MACD histogram > 0, ADX >= 20.
SHORT : mirror image (RSI above 60 then back below and falling, histogram < 0).
SL/TP : SL = 1.5 x ATR from the entry reference (ask for LONG, bid for SHORT);
        TP = 2 x the SL distance. Volume is NOT decided here (risk/ does that).

Macro (hypothesis v001, ADR 0001 #4): risk_off blocks LONG, risk_on blocks SHORT;
unknown/stale context only lowers confidence unless MACRO_REQUIRED=true.

`confidence` is a heuristic strength score in [0, 1], NOT a probability.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field

from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.domain import TIMEFRAME_MINUTES, Side, Timeframe
from trading_system.macro.macro_context import MacroContext
from trading_system.strategy import indicators as ind
from trading_system.strategy.signals import MarketState, Signal


class BaselineParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "baseline-v001"
    timeframe: Timeframe = Timeframe.M15
    ema_fast: int = 50
    ema_slow: int = 200
    rsi_period: int = 14
    rsi_pullback_long: float = 40.0
    rsi_pullback_short: float = 60.0
    rsi_lookback: int = 5
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14
    adx_period: int = 14
    adx_min: float = 20.0
    sl_atr_mult: float = Field(default=1.5, gt=0)
    reward_risk: float = Field(default=2.0, gt=0)
    max_spread_points: int = 30
    allow_short: bool = True
    macro_required: bool = False
    macro_unknown_penalty: float = Field(default=0.8, gt=0, le=1)
    macro_blocks_counter_trend: bool = True

    @property
    def min_bars(self) -> int:
        # EMA200 seeded with an SMA needs ~3x its period to forget the seed.
        return self.ema_slow * 3


@dataclass(frozen=True)
class IndicatorSnapshot:
    """Indicator values on the last closed bar (and what the rules need before it)."""

    close: float
    ema_fast: float | None
    ema_slow: float | None
    rsi: float | None
    rsi_prev: float | None
    rsi_window_min: float | None  # min RSI over the lookback bars before the last
    rsi_window_max: float | None
    macd_hist: float | None
    atr: float | None
    adx: float | None

    @property
    def ready(self) -> bool:
        return self.values() is not None

    def values(self) -> Ready | None:
        fields = (
            self.ema_fast, self.ema_slow, self.rsi, self.rsi_prev, self.rsi_window_min,
            self.rsi_window_max, self.macd_hist, self.atr, self.adx,
        )
        if any(v is None for v in fields):
            return None
        return Ready(self.close, *(float(v) for v in fields if v is not None))


@dataclass(frozen=True)
class Ready:
    """Same values as IndicatorSnapshot, guaranteed non-null."""

    close: float
    ema_fast: float
    ema_slow: float
    rsi: float
    rsi_prev: float
    rsi_window_min: float
    rsi_window_max: float
    macd_hist: float
    atr: float
    adx: float


def snapshot(bars: Sequence[Bar], p: BaselineParams) -> IndicatorSnapshot:
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    rsi = ind.rsi(closes, p.rsi_period)
    window = [v for v in rsi[-1 - p.rsi_lookback:-1] if v is not None]
    full_window = len(window) == p.rsi_lookback
    _, _, hist = ind.macd(closes, p.macd_fast, p.macd_slow, p.macd_signal)
    adx, _, _ = ind.adx(highs, lows, closes, p.adx_period)
    return IndicatorSnapshot(
        close=closes[-1],
        ema_fast=ind.ema(closes, p.ema_fast)[-1],
        ema_slow=ind.ema(closes, p.ema_slow)[-1],
        rsi=rsi[-1],
        rsi_prev=rsi[-2] if len(rsi) > 1 else None,
        rsi_window_min=min(window) if full_window else None,
        rsi_window_max=max(window) if full_window else None,
        macd_hist=hist[-1],
        atr=ind.atr(highs, lows, closes, p.atr_period)[-1],
        adx=adx[-1],
    )


def snapshot_series(bars: Sequence[Bar], p: BaselineParams) -> list[IndicatorSnapshot | None]:
    """Snapshots for every bar, computing each indicator series once (for backtests).

    Indicators are causal (tests/unit/test_indicators.py::test_no_look_ahead), so the
    snapshot at bar i only depends on bars 0..i. Bars before `min_bars` get None, the
    same warm-up the live path enforces.
    """
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    ema_fast, ema_slow = ind.ema(closes, p.ema_fast), ind.ema(closes, p.ema_slow)
    rsi = ind.rsi(closes, p.rsi_period)
    _, _, hist = ind.macd(closes, p.macd_fast, p.macd_slow, p.macd_signal)
    atr = ind.atr(highs, lows, closes, p.atr_period)
    adx, _, _ = ind.adx(highs, lows, closes, p.adx_period)

    out: list[IndicatorSnapshot | None] = []
    for i in range(len(bars)):
        if i + 1 < p.min_bars:
            out.append(None)
            continue
        window = [v for v in rsi[i - p.rsi_lookback:i] if v is not None]
        full = len(window) == p.rsi_lookback
        out.append(IndicatorSnapshot(
            close=closes[i], ema_fast=ema_fast[i], ema_slow=ema_slow[i], rsi=rsi[i],
            rsi_prev=rsi[i - 1], rsi_window_min=min(window) if full else None,
            rsi_window_max=max(window) if full else None, macd_hist=hist[i], atr=atr[i],
            adx=adx[i],
        ))
    return out


def _long_checks(s: Ready, p: BaselineParams) -> dict[str, bool]:
    return {
        "ema_trend_up": s.ema_fast > s.ema_slow,
        "close_above_ema_fast": s.close > s.ema_fast,
        "rsi_recovering": s.rsi_window_min < p.rsi_pullback_long < s.rsi and s.rsi > s.rsi_prev,
        "macd_bullish": s.macd_hist > 0,
        "adx_trending": s.adx >= p.adx_min,
    }


def _short_checks(s: Ready, p: BaselineParams) -> dict[str, bool]:
    return {
        "ema_trend_down": s.ema_fast < s.ema_slow,
        "close_below_ema_fast": s.close < s.ema_fast,
        "rsi_rolling_over": (
            s.rsi_window_max > p.rsi_pullback_short > s.rsi and s.rsi < s.rsi_prev
        ),
        "macd_bearish": s.macd_hist < 0,
        "adx_trending": s.adx >= p.adx_min,
    }


def signal_id(p: BaselineParams, symbol: str, bar: Bar) -> str:
    raw = f"{p.version}|{symbol}|{p.timeframe.value}|{bar.time.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _data_holds(
    snap: IndicatorSnapshot | None, last_bar: Bar | None, tick: Tick, p: BaselineParams
) -> list[str]:
    if last_bar is None or snap is None:
        return ["insufficient_data"]
    holds: list[str] = []
    tf = timedelta(minutes=TIMEFRAME_MINUTES[p.timeframe])
    bar_close = last_bar.time + tf
    if tick.time < bar_close:
        holds.append("bar_not_closed")
    elif tick.time - bar_close > tf:
        holds.append("stale_data")
    if not snap.ready:
        holds.append("indicators_not_ready")
    return holds


def _context_holds(
    tick: Tick, spec: SymbolSpec, macro: MacroContext, state: MarketState, p: BaselineParams
) -> list[str]:
    rules = [
        (tick.spread_points > p.max_spread_points, "spread_too_wide"),
        (state.has_open_position, "position_open"),
        (state.risk_blocked, "risk_blocked"),
        (not spec.trade_allowed, "symbol_not_tradeable"),
        (_macro_unavailable(macro) and p.macro_required, "macro_unavailable"),
    ]
    return [name for violated, name in rules if violated]


def _macro_unavailable(macro: MacroContext) -> bool:
    return macro.risk_regime == "unknown" or macro.data_stale


@dataclass(frozen=True)
class _Setup:
    side: Side
    reasons: list[str]
    score: int
    holds: list[str]


def _setup(ready: Ready, spec: SymbolSpec, macro: MacroContext, p: BaselineParams) -> _Setup:
    longs, shorts = _long_checks(ready, p), _short_checks(ready, p)
    n_long, n_short = sum(longs.values()), sum(shorts.values())
    score = round(100 * max(n_long, n_short) / len(longs))
    if all(longs.values()):
        contradiction = p.macro_blocks_counter_trend and macro.risk_regime == "risk_off"
        return _Setup(Side.LONG, list(longs), score,
                      ["macro_contradiction"] if contradiction else [])
    if all(shorts.values()) and p.allow_short:
        if not spec.short_allowed:
            return _Setup(Side.HOLD, list(shorts), score, ["short_not_allowed"])
        contradiction = p.macro_blocks_counter_trend and macro.risk_regime == "risk_on"
        return _Setup(Side.SHORT, list(shorts), score,
                      ["macro_contradiction"] if contradiction else [])
    best = longs if n_long >= n_short else shorts
    detail = [f"{k}={'ok' if v else 'no'}" for k, v in best.items()]
    return _Setup(Side.HOLD, detail, score, ["no_setup"])


def decide(
    snap: IndicatorSnapshot | None,
    last_bar: Bar | None,
    tick: Tick,
    spec: SymbolSpec,
    macro: MacroContext,
    state: MarketState,
    p: BaselineParams,
    symbol: str,
) -> Signal:
    """Pure decision function. Every reason to stay out is reported in hold_reasons."""
    holds = _data_holds(snap, last_bar, tick, p) + _context_holds(tick, spec, macro, state, p)
    ready = snap.values() if snap is not None else None
    setup = _setup(ready, spec, macro, p) if ready is not None else None
    if setup is not None:
        holds += setup.holds

    common = {
        "signal_id": signal_id(p, symbol, last_bar) if last_bar is not None else "no-bar",
        "symbol": symbol,
        "timeframe": p.timeframe,
        "bar_time": last_bar.time if last_bar is not None else tick.time,
        "technical_score": setup.score if setup is not None else 0,
        "macro_regime": macro.risk_regime,
        "strategy_version": p.version,
    }
    reasons = list(setup.reasons) if setup is not None else []

    if setup is None or ready is None or setup.side is Side.HOLD or holds:
        return Signal(side=Side.HOLD, confidence=0.0, reasons=tuple(reasons),
                      hold_reasons=tuple(dict.fromkeys(holds)) or ("no_setup",), **common)

    side = setup.side
    entry = tick.ask if side is Side.LONG else tick.bid
    dist = p.sl_atr_mult * ready.atr
    sign = 1 if side is Side.LONG else -1
    stop = round(entry - sign * dist, spec.digits)
    target = round(entry + sign * p.reward_risk * dist, spec.digits)

    # Strength heuristic: ADX from the minimum up to +20 points maps 0.5 -> 1.0.
    confidence = 0.5 + 0.5 * min(1.0, max(0.0, (ready.adx - p.adx_min) / 20))
    if _macro_unavailable(macro):
        confidence *= p.macro_unknown_penalty
        reasons.append("macro_unknown_penalty")
    return Signal(side=side, confidence=round(confidence, 4), reasons=tuple(reasons),
                  entry_ref=entry, stop_loss=stop, take_profit=target, **common)


class BaselineStrategy:
    def __init__(self, params: BaselineParams | None = None) -> None:
        self.params = params or BaselineParams()
        self.version = self.params.version

    def evaluate(
        self,
        bars: Sequence[Bar],
        tick: Tick,
        spec: SymbolSpec,
        macro: MacroContext,
        state: MarketState,
    ) -> Signal:
        p = self.params
        enough = len(bars) >= p.min_bars
        snap = snapshot(bars, p) if enough else None
        last = bars[-1] if bars else None
        return decide(snap, last if enough else None, tick, spec, macro, state, p, spec.symbol)
