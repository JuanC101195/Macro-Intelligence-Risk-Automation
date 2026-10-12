"""Technical indicators (docs/implementation-plan.md task 4.1).

Conventions (same as TA-Lib / Wilder):
- Every function returns a list aligned with its input; positions without enough
  history are None, so a half-warmed indicator can never be used by mistake.
- EMA is seeded with the SMA of the first `period` values.
- RSI, ATR and ADX use Wilder smoothing (alpha = 1/period).
- Value i only depends on inputs 0..i (no look-ahead); tests check this.
"""

from __future__ import annotations

from collections.abc import Sequence

Series = list[float | None]


def _check_period(period: int) -> None:
    if period < 1:
        raise ValueError("period must be >= 1")


def sma(values: Sequence[float], period: int) -> Series:
    _check_period(period)
    out: Series = [None] * len(values)
    window = 0.0
    for i, v in enumerate(values):
        window += v
        if i >= period:
            window -= values[i - period]
        if i >= period - 1:
            out[i] = window / period
    return out


def ema(values: Sequence[float], period: int) -> Series:
    _check_period(period)
    out: Series = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def _ema_of_optional(values: Series, period: int) -> Series:
    """EMA over a series that starts with None (e.g. the MACD line)."""
    start = next((i for i, v in enumerate(values) if v is not None), len(values))
    tail = [v for v in values[start:] if v is not None]
    return [None] * start + ema(tail, period)


def _wilder(values: Sequence[float], period: int, first: int) -> Series:
    """Wilder smoothing of values[first:], seeded with their simple mean."""
    out: Series = [None] * len(values)
    if len(values) - first < period:
        return out
    prev = sum(values[first:first + period]) / period
    out[first + period - 1] = prev
    for i in range(first + period, len(values)):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def rsi(closes: Sequence[float], period: int = 14) -> Series:
    _check_period(period)
    n = len(closes)
    out: Series = [None] * n
    if n <= period:
        return out
    gains = [0.0] + [max(closes[i] - closes[i - 1], 0.0) for i in range(1, n)]
    losses = [0.0] + [max(closes[i - 1] - closes[i], 0.0) for i in range(1, n)]
    avg_gain = _wilder(gains, period, first=1)
    avg_loss = _wilder(losses, period, first=1)
    for i in range(n):
        g, loss = avg_gain[i], avg_loss[i]
        if g is None or loss is None:
            continue
        if loss == 0:
            out[i] = 100.0 if g > 0 else 50.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + g / loss)
    return out


def macd(
    closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Series, Series, Series]:
    """Returns (macd line, signal line, histogram)."""
    if fast >= slow:
        raise ValueError("fast period must be shorter than slow period")
    ema_fast, ema_slow = ema(closes, fast), ema(closes, slow)
    line: Series = [
        f - s if f is not None and s is not None else None
        for f, s in zip(ema_fast, ema_slow, strict=True)
    ]
    sig = _ema_of_optional(line, signal)
    hist: Series = [
        m - s if m is not None and s is not None else None for m, s in zip(line, sig, strict=True)
    ]
    return line, sig, hist


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> Series:
    out: Series = [None] * len(closes)
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        out[i] = max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev))
    return out


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> Series:
    _check_period(period)
    tr = true_range(highs, lows, closes)
    return _wilder([v or 0.0 for v in tr], period, first=1)


def _directional_movement(
    highs: Sequence[float], lows: Sequence[float]
) -> tuple[list[float], list[float]]:
    n = len(highs)
    plus_dm, minus_dm = [0.0] * n, [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
    return plus_dm, minus_dm


def _wilder_sum(values: list[float], period: int) -> Series:
    """Wilder running sum (not mean) of values[1:], as in Wilder's original ADX."""
    n = len(values)
    out: Series = [None] * n
    if n - 1 < period:
        return out
    prev = sum(values[1:period + 1])
    out[period] = prev
    for i in range(period + 1, n):
        prev = prev - prev / period + values[i]
        out[i] = prev
    return out


def _smooth_sparse(values: list[float], index: list[int], n: int, period: int) -> Series:
    """Wilder-smooth `values` (located at `index` positions) into a series of length n."""
    out: Series = [None] * n
    if len(values) < period:
        return out
    prev = sum(values[:period]) / period
    out[index[period - 1]] = prev
    for k in range(period, len(values)):
        prev = (prev * (period - 1) + values[k]) / period
        out[index[k]] = prev
    return out


def adx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> tuple[Series, Series, Series]:
    """Returns (ADX, +DI, -DI). ADX needs 2*period bars before its first value."""
    _check_period(period)
    n = len(closes)
    plus_dm, minus_dm = _directional_movement(highs, lows)
    tr = [v or 0.0 for v in true_range(highs, lows, closes)]
    tr_s, pdm_s = _wilder_sum(tr, period), _wilder_sum(plus_dm, period)
    mdm_s = _wilder_sum(minus_dm, period)

    plus_di: Series = [None] * n
    minus_di: Series = [None] * n
    dx: list[float] = []
    dx_index: list[int] = []
    for i, (t, p, m) in enumerate(zip(tr_s, pdm_s, mdm_s, strict=True)):
        if t is None or p is None or m is None or t == 0:
            continue
        pdi, mdi = 100.0 * p / t, 100.0 * m / t
        plus_di[i], minus_di[i] = pdi, mdi
        total = pdi + mdi
        dx.append(0.0 if total == 0 else 100.0 * abs(pdi - mdi) / total)
        dx_index.append(i)
    return _smooth_sparse(dx, dx_index, n, period), plus_di, minus_di