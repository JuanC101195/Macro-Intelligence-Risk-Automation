"""Statistical arbitrage AUDUSD-NZDUSD `pairs-v001` (ADR 0007 and its addendum).

On the hours where BOTH legs have a bar (common index k), using only data up to k:
- every `beta_every` bars: OLS with constant of ln(A) on ln(B) over the last `beta_window`
  bars -> beta; Engle-Granger: ADF (no constant, 1 lag) on those residuals, cointegrated
  if t < MacKinnon (2010) 5% critical value for 2 variables with constant;
- spread s = ln(A) - beta * ln(B) over the last `z_window` bars with the current beta;
  z = (s_k - mean) / std.
Entry: z >= +entry_z -> short spread (sell A, buy B); z <= -entry_z -> long spread.
Exit: z crosses 0, |z| >= stop_z, or `max_bars` common bars since the entry.
Pure Python: the project does not depend on numpy/statsmodels.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from trading_system.broker.contracts import Bar
from trading_system.strategy import indicators as ind


class PairsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "pairs-v001"
    leg_a: str = "AUDUSD"
    leg_b: str = "NZDUSD"
    beta_window: int = Field(default=1_000, ge=50)
    beta_every: int = Field(default=24, ge=1)
    z_window: int = Field(default=240, ge=20)
    entry_z: float = Field(default=2.0, gt=0)
    stop_z: float = Field(default=4.0, gt=0)
    max_bars: int = Field(default=120, ge=1)
    coint_filter: bool = True
    atr_period: int = 20
    stop_atr: float = Field(default=4.0, gt=0)  # protective stop of each leg
    target_atr: float = Field(default=8.0, gt=0)  # contractual, non-binding
    risk_fraction: float = Field(default=0.0025, gt=0)  # per pair, |z| from entry_z to stop_z


# --- statistics ---------------------------------------------------------------------------


def ols(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    """(alpha, beta) of y = alpha + beta * x."""
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    if sxx == 0:
        raise ValueError("constant regressor")
    beta = sxy / sxx
    return my - beta * mx, beta


def adf_t(series: Sequence[float]) -> float:
    """ADF t-statistic of gamma in  d_e[t] = gamma * e[t-1] + phi * d_e[t-1] + u  (no constant)."""
    d = [series[i] - series[i - 1] for i in range(1, len(series))]
    # Rows t = 2..n-1: target d[t-1], regressors e[t-1] and d[t-2].
    y = d[1:]
    x1 = list(series[1:-1])
    x2 = d[:-1]
    s11 = sum(a * a for a in x1)
    s22 = sum(b * b for b in x2)
    s12 = sum(a * b for a, b in zip(x1, x2, strict=True))
    s1y = sum(a * c for a, c in zip(x1, y, strict=True))
    s2y = sum(b * c for b, c in zip(x2, y, strict=True))
    det = s11 * s22 - s12 * s12
    if det <= 0:
        raise ValueError("singular ADF regression")
    gamma = (s1y * s22 - s2y * s12) / det
    phi = (s2y * s11 - s1y * s12) / det
    rss = sum((c - gamma * a - phi * b) ** 2 for a, b, c in zip(x1, x2, y, strict=True))
    sigma2 = rss / (len(y) - 2)
    se = math.sqrt(sigma2 * s22 / det)
    return gamma / se


def engle_granger_crit_5pct(n_obs: int) -> float:
    """MacKinnon (2010), table 2: cointegration t-test, N=2 variables, constant, 5%."""
    return -3.33613 - 6.1101 / n_obs - 6.823 / n_obs ** 2


# --- strategy -----------------------------------------------------------------------------


@dataclass(frozen=True)
class PairState:
    index: int  # position in the common timeline
    beta: float
    z: float
    spread_std: float
    cointegrated: bool


class PairsStrategy:
    def __init__(self, params: PairsParams, bars: Mapping[str, Sequence[Bar]]) -> None:
        self.params = params
        a = {b.time: b.close for b in bars[params.leg_a]}
        b = {x.time: x.close for x in bars[params.leg_b]}
        self.times: list[datetime] = sorted(a.keys() & b.keys())
        self._index = {t: k for k, t in enumerate(self.times)}
        self._la = [math.log(a[t]) for t in self.times]
        self._lb = [math.log(b[t]) for t in self.times]
        self._atr: dict[tuple[str, datetime], float] = {}
        for sym in (params.leg_a, params.leg_b):
            series = bars[sym]
            values = ind.atr([x.high for x in series], [x.low for x in series],
                             [x.close for x in series], params.atr_period)
            for bar, value in zip(series, values, strict=True):
                if value is not None:
                    self._atr[(sym, bar.time)] = value
        self._states = self._precompute()

    def _precompute(self) -> dict[int, PairState]:
        p = self.params
        states: dict[int, PairState] = {}
        beta: float | None = None
        coint = False
        crit = engle_granger_crit_5pct(p.beta_window - 2)
        first = max(p.beta_window, p.z_window) - 1
        for k in range(first, len(self.times)):
            if beta is None or (k - first) % p.beta_every == 0:
                xs = self._lb[k - p.beta_window + 1:k + 1]
                ys = self._la[k - p.beta_window + 1:k + 1]
                alpha, beta = ols(xs, ys)
                resid = [y - alpha - beta * x for x, y in zip(xs, ys, strict=True)]
                coint = adf_t(resid) < crit
            assert beta is not None
            spreads = [self._la[j] - beta * self._lb[j] for j in range(k - p.z_window + 1, k + 1)]
            mean = sum(spreads) / len(spreads)
            std = math.sqrt(sum((s - mean) ** 2 for s in spreads) / (len(spreads) - 1))
            if std > 0:
                states[k] = PairState(k, beta, (spreads[-1] - mean) / std, std, coint)
        return states

    # --- queries used by the pair engine --------------------------------------------------

    def state(self, t: datetime) -> PairState | None:
        k = self._index.get(t)
        return None if k is None else self._states.get(k)

    def index(self, t: datetime) -> int | None:
        return self._index.get(t)

    def atr(self, symbol: str, t: datetime) -> float | None:
        return self._atr.get((symbol, t))

    def entry(self, t: datetime) -> tuple[int, str | None]:
        """(direction, hold reason): +1 long spread (buy A, sell B), -1 short spread."""
        s = self.state(t)
        if s is None:
            return 0, "indicators_not_ready"
        if s.beta <= 0:
            return 0, "beta_not_positive"
        if abs(s.z) < self.params.entry_z:
            return 0, "z_inside_band"
        if self.params.coint_filter and not s.cointegrated:
            return 0, "not_cointegrated"
        return (-1 if s.z > 0 else 1), None

    def should_exit(self, t: datetime, direction: int, entry_index: int) -> bool:
        s = self.state(t)
        if s is None:
            return False
        reverted = s.z >= 0 if direction > 0 else s.z <= 0
        return (reverted or abs(s.z) >= self.params.stop_z
                or s.index - entry_index >= self.params.max_bars)
