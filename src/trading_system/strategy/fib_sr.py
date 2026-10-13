"""Fibonacci retracement + support/resistance on gold, H1 analysis and M5 entry.

`fibsr-xau-v001` (ADR 0011), a partner's discretionary method turned into rules:
- H1 swings (ZigZag of k x ATR) give the trend (two lower highs and lows, or higher)
  and the last leg; M5 swings of the last 24 h must show the same trend.
- Entry band: 50 %-61.8 % retracement of a leg of at least 10 x ATR(H1), overlapping a
  horizontal zone (>= 2 wick fractals) or a diagonal line (>= 3 touches) of the last
  week of H1 bars, on the correct side (resistance to sell, support to buy).
- Trigger: an M5 engulfing or long-wick rejection candle with the trend inside the band.
- Stop at 78.6 %, target at 0 %; at +1 R the stop locks +0.5 R, then trails behind each
  new confirmed M5 swing.
Everything is precomputed once; no value uses a bar that had not closed (an H1 bar is
used only after it closes, a swing only from the bar that confirms it).
"""

from __future__ import annotations

from array import array
from bisect import bisect_right
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.domain import Side, Timeframe, bracket_error
from trading_system.macro.macro_context import MacroContext
from trading_system.strategy import indicators as ind
from trading_system.strategy.signals import MarketState, Signal

BrokerSide = Literal["buy", "sell"]
H1 = timedelta(hours=1)
M5 = timedelta(minutes=5)


class FibSrParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "fibsr-xau-v001"
    timeframe: Timeframe = Timeframe.M5
    atr_period: int = 14
    zigzag_atr: float = Field(default=4.0, gt=0)  # H1 swings
    m5_zigzag_atr: float = Field(default=4.0, gt=0)
    min_leg_atr: float = Field(default=10.0, gt=0)
    band_low: float = 0.5  # retracement fractions of the leg
    band_high: float = 0.618
    stop_level: float = 0.786
    sr_lookback: int = 120  # H1 bars (one trading week)
    fractal_wing: int = 3
    touch_tol_atr: float = Field(default=0.5, gt=0)
    min_zone_touches: int = 2
    min_line_touches: int = 3
    line_min_gap: int = 10
    m5_trend_bars: int = 288  # 24 h of M5 bars
    pin_wick_body: float = 2.0
    lock_at_r: float = 1.0
    lock_r: float = 0.5


@dataclass(frozen=True)
class Pivot:
    kind: Literal["H", "L"]
    price: float
    idx: int  # bar of the extreme
    confirm: int  # first bar at whose close the pivot is known


def zigzag(highs: Sequence[float], lows: Sequence[float], atr: Sequence[float | None],
           mult: float) -> list[Pivot]:
    """Alternating swings confirmed by a reversal of `mult` x ATR (ATR of the confirming bar)."""
    pivots: list[Pivot] = []
    state = 0  # 0 unknown, 1 tracking a high, -1 tracking a low
    hi, hi_i, lo, lo_i = highs[0], 0, lows[0], 0
    for i in range(len(highs)):
        if highs[i] > hi:
            hi, hi_i = highs[i], i
        if lows[i] < lo:
            lo, lo_i = lows[i], i
        a = atr[i]
        if a is None:
            continue
        threshold = mult * a
        if state >= 0 and hi_i < i and hi - lows[i] >= threshold and (state == 1 or hi_i > lo_i):
            pivots.append(Pivot("H", hi, hi_i, i))
            state, lo, lo_i = -1, lows[i], i
        elif state <= 0 and lo_i < i and highs[i] - lo >= threshold \
                and (state == -1 or lo_i > hi_i):
            pivots.append(Pivot("L", lo, lo_i, i))
            state, hi, hi_i = 1, highs[i], i
    return pivots


def fractals(values: Sequence[float], wing: int, highs: bool) -> list[tuple[int, float]]:
    """(index, price) of wick fractals; known `wing` bars after the index."""
    out = []
    for k in range(wing, len(values) - wing):
        v = values[k]
        left = values[k - wing:k]
        right = values[k + 1:k + wing + 1]
        if highs:
            is_fractal = v > max(left) and v >= max(right)
        else:
            is_fractal = v < min(left) and v <= min(right)
        if is_fractal:
            out.append((k, v))
    return out


@dataclass(frozen=True)
class Leg:
    side: Side  # trade direction (SHORT in a downtrend)
    band_lo: float
    band_hi: float
    stop: float
    target: float
    start_price: float  # 100 % pivot
    start_time: datetime
    end_time: datetime  # 0 % pivot


@dataclass(frozen=True)
class Setup:
    side: Side
    stop: float
    target: float
    leg: Leg
    level: str  # the zone or line that matched the band (for review charts)


def _trend(pivots: Sequence[Pivot]) -> int:
    highs = [p.price for p in pivots if p.kind == "H"][-2:]
    lows = [p.price for p in pivots if p.kind == "L"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return 0
    if highs[1] < highs[0] and lows[1] < lows[0]:
        return -1
    if highs[1] > highs[0] and lows[1] > lows[0]:
        return 1
    return 0


class FibSrStrategy:
    def __init__(self, params: FibSrParams, m5: Mapping[str, Sequence[Bar]],
                 h1: Mapping[str, Sequence[Bar]]) -> None:
        self.params = params
        self.hold_counts: Counter[str] = Counter()
        self._setups: dict[tuple[str, datetime], Setup] = {}
        self._m5_times: dict[str, list[datetime]] = {}
        self._m5_pivots: dict[str, list[Pivot]] = {}
        self._m5_confirms: dict[str, array[int]] = {}
        for sym in m5:
            self._prepare(sym, m5[sym], h1[sym])

    # --- precomputation --------------------------------------------------------------

    def _prepare(self, sym: str, m5: Sequence[Bar], h1: Sequence[Bar]) -> None:
        p = self.params
        hh = [b.high for b in h1]
        hl = [b.low for b in h1]
        hc = [b.close for b in h1]
        h_atr = ind.atr(hh, hl, hc, p.atr_period)
        h_piv = zigzag(hh, hl, h_atr, p.zigzag_atr)
        h_conf = [pv.confirm for pv in h_piv]
        ctx = _H1Context(p, h1, hh, hl, hc, h_atr, h_piv, h_conf)

        mh = [b.high for b in m5]
        ml = [b.low for b in m5]
        mc = [b.close for b in m5]
        m_atr = ind.atr(mh, ml, mc, p.atr_period)
        m_piv = zigzag(mh, ml, m_atr, p.m5_zigzag_atr)
        m_conf = array("q", [pv.confirm for pv in m_piv])
        self._m5_times[sym] = [b.time for b in m5]
        self._m5_pivots[sym] = m_piv
        self._m5_confirms[sym] = m_conf

        j = -1
        hour_hi, hour_lo = float("-inf"), float("inf")
        for i, bar in enumerate(m5):
            close_t = bar.time + M5
            moved = False
            while j + 1 < len(h1) and h1[j + 1].time + H1 <= close_t:
                j += 1
                moved = True
            if moved:
                hour_hi, hour_lo = float("-inf"), float("inf")
            hour_hi, hour_lo = max(hour_hi, bar.high), min(hour_lo, bar.low)
            if j < 0:
                continue
            setup, reason = self._setup_at(ctx, j, i, m5, m_piv, m_conf, hour_hi, hour_lo)
            if setup is not None:
                self._setups[(sym, bar.time)] = setup
            elif reason:
                self.hold_counts[reason] += 1

    def _setup_at(self, ctx: _H1Context, j: int, i: int, m5: Sequence[Bar],
                  m_piv: Sequence[Pivot], m_conf: array[int], hour_hi: float,
                  hour_lo: float) -> tuple[Setup | None, str]:
        leg = ctx.leg(j)
        if leg is None:
            return None, ""
        short = leg.side is Side.SHORT
        # Invalidated within the current hour: beyond 78.6 % or a new extreme past 0 %.
        if short:
            invalid = hour_hi > leg.stop or hour_lo < leg.target
        else:
            invalid = hour_lo < leg.stop or hour_hi > leg.target
        if invalid:
            return None, "leg_invalidated"
        bar = m5[i]
        if not _in_band(bar, leg, short) or i == 0 or not _trigger(m5[i - 1], bar, short,
                                                                   self.params.pin_wick_body):
            return None, ""
        if _m5_trend(m_piv, m_conf, i, self.params.m5_trend_bars) != (-1 if short else 1):
            return None, "m5_trend_disagrees"
        level = ctx.confluence(j, leg)
        if level is None:
            return None, "no_support_resistance"
        return Setup(leg.side, leg.stop, leg.target, leg, level), ""

    # --- engine hooks ------------------------------------------------------------------

    def decide(self, _snap: Any, last_bar: Bar | None, tick: Tick, spec: SymbolSpec,
               macro: MacroContext, state: MarketState, _params: Any, symbol: str
               ) -> Signal:
        assert last_bar is not None
        common: dict[str, Any] = {
            "signal_id": f"{self.params.version}-{symbol}-{last_bar.time:%Y%m%d%H%M}",
            "symbol": symbol, "timeframe": self.params.timeframe, "bar_time": last_bar.time,
            "technical_score": 0, "macro_regime": macro.risk_regime,
            "strategy_version": self.params.version,
        }
        setup = self._setups.get((symbol, last_bar.time))
        hold: str | None = None
        if state.has_open_position:
            hold = "position_open"
        elif setup is None:
            hold = "no_setup"
        if hold is None and setup is not None:
            is_long = setup.side is Side.LONG
            entry = tick.ask if is_long else tick.bid
            stop = round(setup.stop, spec.digits)
            target = round(setup.target, spec.digits)
            if not bracket_error(is_long, entry, stop, target):
                return Signal(side=setup.side, confidence=0.5,
                              reasons=("fib_band_sr_confluence_m5_trigger",),
                              entry_ref=entry, stop_loss=stop, take_profit=target, **common)
            hold = "invalid_bracket"
        return Signal(side=Side.HOLD, confidence=0.0, hold_reasons=(hold or "no_setup",),
                      **common)

    def stop_update(self, symbol: str, bar: Bar, side: BrokerSide, entry_time: datetime,
                    entry: float, initial_stop: float, current: float) -> float | None:
        """Lock +0.5 R at +1 R, then trail behind confirmed M5 swings after the entry."""
        p = self.params
        risk = abs(entry - initial_stop)
        sign = 1 if side == "buy" else -1
        lock = entry + sign * p.lock_r * risk
        locked = sign * (current - lock) >= -1e-9
        if not locked:
            gained = sign * (bar.close - entry) >= p.lock_at_r * risk
            return lock if gained else None
        times = self._m5_times[symbol]
        i = bisect_right(times, bar.time) - 1
        entry_i = bisect_right(times, entry_time) - 1
        pivots = self._m5_pivots[symbol]
        n = bisect_right(self._m5_confirms[symbol], i)
        kind = "L" if side == "buy" else "H"
        for pv in reversed(pivots[:n]):
            if pv.idx < entry_i:
                break
            if pv.kind == kind:
                return pv.price if sign * (pv.price - current) > 0 else None
        return None


def _in_band(bar: Bar, leg: Leg, short: bool) -> bool:
    if short:
        return bar.high >= leg.band_lo and bar.close < leg.stop and bar.close > leg.target
    return bar.low <= leg.band_hi and bar.close > leg.stop and bar.close < leg.target


def _trigger(prev: Bar, bar: Bar, short: bool, wick_body: float) -> bool:
    body = abs(bar.close - bar.open)
    rng = bar.high - bar.low
    if short:
        engulf = prev.close > prev.open and bar.close < bar.open \
            and bar.open >= prev.close and bar.close <= prev.open
        wick = bar.high - max(bar.open, bar.close)
        pin = rng > 0 and wick >= wick_body * body and wick >= 0.5 * rng \
            and bar.close <= (bar.high + bar.low) / 2
    else:
        engulf = prev.close < prev.open and bar.close > bar.open \
            and bar.open <= prev.close and bar.close >= prev.open
        wick = min(bar.open, bar.close) - bar.low
        pin = rng > 0 and wick >= wick_body * body and wick >= 0.5 * rng \
            and bar.close >= (bar.high + bar.low) / 2
    return engulf or pin


def _m5_trend(pivots: Sequence[Pivot], confirms: array[int], i: int, window: int) -> int:
    n = bisect_right(confirms, i)
    recent = [pv for pv in pivots[max(0, n - 8):n] if pv.idx > i - window]
    return _trend(recent)


class _H1Context:
    """Leg and support/resistance as known at the close of H1 bar j (cached per j)."""

    def __init__(self, p: FibSrParams, bars: Sequence[Bar], highs: list[float],
                 lows: list[float], closes: list[float], atr: Sequence[float | None],
                 pivots: list[Pivot], confirms: list[int]) -> None:
        self.p = p
        self.bars = bars
        self.highs, self.lows, self.closes, self.atr = highs, lows, closes, atr
        self.pivots, self.confirms = pivots, confirms
        self.frac_hi = fractals(highs, p.fractal_wing, highs=True)
        self.frac_lo = fractals(lows, p.fractal_wing, highs=False)
        self._legs: dict[int, Leg | None] = {}
        self._sr: dict[tuple[int, Side], tuple[list[tuple[float, float]],
                                                list[tuple[int, float, float, Side]]]] = {}

    def leg(self, j: int) -> Leg | None:
        if j not in self._legs:
            self._legs[j] = self._leg(j)
        return self._legs[j]

    def _leg(self, j: int) -> Leg | None:
        a = self.atr[j]
        n = bisect_right(self.confirms, j)
        if a is None or n < 4:
            return None
        known = self.pivots[:n]
        trend = _trend(known[-6:])
        last, prev = known[-1], known[-2]
        if trend == 0 or (trend == -1) != (last.kind == "L"):
            return None
        size = abs(prev.price - last.price)
        if size < self.p.min_leg_atr * a:
            return None
        after_hi = max(self.highs[last.idx + 1:j + 1], default=float("-inf"))
        after_lo = min(self.lows[last.idx + 1:j + 1], default=float("inf"))
        p = self.p
        times = (prev.price, self.bars[prev.idx].time, self.bars[last.idx].time)
        if trend == -1:
            lo = last.price
            leg = Leg(Side.SHORT, lo + p.band_low * size, lo + p.band_high * size,
                      lo + p.stop_level * size, lo, *times)
            return None if after_hi > leg.stop or after_lo < lo else leg
        hi = last.price
        leg = Leg(Side.LONG, hi - p.band_high * size, hi - p.band_low * size,
                  hi - p.stop_level * size, hi, *times)
        return None if after_lo < leg.stop or after_hi > hi else leg

    def confluence(self, j: int, leg: Leg) -> str | None:
        """The first zone or line that overlaps the band, described; None if none does."""
        a = self.atr[j]
        if a is None:
            return None
        tol = self.p.touch_tol_atr * a
        zones, lines = self._levels(j, leg.side)
        for z_lo, z_hi in zones:
            if z_lo <= leg.band_hi and z_hi >= leg.band_lo:
                return f"zone {z_lo:.2f}-{z_hi:.2f}"
        for k0, p0, slope, _ in lines:
            value = self._line_at(k0, p0, slope, j)
            if leg.band_lo - tol <= value <= leg.band_hi + tol:
                return (f"line {self.bars[k0].time:%Y-%m-%d %H:%M} {p0:.2f} "
                        f"slope {slope:+.3f}/h now {value:.2f}")
        return None

    @staticmethod
    def _line_at(k0: int, p0: float, slope: float, k: int) -> float:
        return p0 + slope * (k - k0)

    def _levels(self, j: int, side: Side) -> tuple[list[tuple[float, float]],
                                                   list[tuple[int, float, float, Side]]]:
        """Zones and lines usable for `side` (resistance for SHORT, support for LONG)."""
        key = (j, side)
        if key in self._sr:
            return self._sr[key]
        p = self.p
        a = self.atr[j] or 0.0
        tol = p.touch_tol_atr * a
        first = j - p.sr_lookback + 1
        highs = [(k, v) for k, v in self.frac_hi if first <= k and k + p.fractal_wing <= j]
        lows = [(k, v) for k, v in self.frac_lo if first <= k and k + p.fractal_wing <= j]
        zones = _zones(highs if side is Side.SHORT else lows, tol, p.min_zone_touches)
        lines = [ln for ln in self._lines(highs, tol, j, Side.SHORT) +
                 self._lines(lows, tol, j, Side.LONG) if ln[3] is side]
        self._sr[key] = (zones, lines)
        return zones, lines

    def _lines(self, points: list[tuple[int, float]], tol: float, j: int, role: Side
               ) -> list[tuple[int, float, float, Side]]:
        """Diagonal lines through same-kind fractals; role flips once broken and retested."""
        p = self.p
        out = []
        for x in range(len(points)):
            for y in range(x + 1, len(points)):
                (k0, p0), (k1, p1) = points[x], points[y]
                if k1 - k0 < p.line_min_gap:
                    continue
                slope = (p1 - p0) / (k1 - k0)
                touches = [k for k, v in points
                           if abs(self._line_at(k0, p0, slope, k) - v) <= tol]
                if len(touches) < p.min_line_touches:
                    continue
                final = self._role(k0, p0, slope, min(touches), max(touches), j, tol, role)
                if final is not None:
                    out.append((k0, p0, slope, final))
        return out

    def _role(self, k0: int, p0: float, slope: float, first: int, last: int, j: int,
              tol: float, role: Side) -> Side | None:
        resistance = role is Side.SHORT
        sign = 1 if resistance else -1  # a close beyond the line: above resistance, below support

        def through(k: int) -> bool:
            return sign * (self.closes[k] - self._line_at(k0, p0, slope, k)) > 0

        if any(through(k) for k in range(first, last + 1)):  # must hold between touches
            return None
        broken_at = next((k for k in range(last + 1, j + 1) if through(k)), None)
        if broken_at is None:
            return role
        retests = self.frac_lo if resistance else self.frac_hi
        retested = any(broken_at < k <= j - self.p.fractal_wing
                       and abs(self._line_at(k0, p0, slope, k) - v) <= tol
                       for k, v in retests)
        if not retested:
            return None
        return Side.LONG if resistance else Side.SHORT


def _zones(points: list[tuple[int, float]], tol: float, min_touches: int
           ) -> list[tuple[float, float]]:
    zones = []
    prices = sorted(v for _, v in points)
    for v in prices:
        group = [w for w in prices if abs(w - v) <= tol]
        if len(group) >= min_touches:
            zones.append((min(group), max(group)))
    return zones
