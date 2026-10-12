"""Market regimes with a Gaussian mixture, `regime-h4-v001` (ADR 0008).

Per instrument and bar, from the last `feature_window` closes (current bar included):
  vol = ln(sample std of log returns), er = Kaufman efficiency ratio.
A K-component, full-covariance 2-D Gaussian mixture is fitted by EM on standardized
features of the previous `train_years` (the fit never sees the bars it labels) and
refitted at the first bar of January and July. The "trend" regime is the component with
the highest mean er. Pure Python: the project does not depend on numpy/scikit-learn.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from trading_system.broker.contracts import Bar

Point = tuple[float, float]
Cov = tuple[float, float, float]  # (sxx, sxy, syy)
LOG_2PI = math.log(2 * math.pi)
START_TOLERANCE = timedelta(days=7)  # first bar may come a few days after the window start


class RegimeParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    components: int = Field(default=3, ge=2, le=6)
    feature_window: int = Field(default=30, ge=5)
    train_years: int = Field(default=2, ge=1)
    max_iter: int = Field(default=200, ge=1)
    tol: float = Field(default=1e-6, gt=0)
    reg: float = Field(default=1e-6, ge=0)


# --- features -----------------------------------------------------------------------------


def features(closes: Sequence[float], window: int) -> list[Point | None]:
    """(vol, er) per index, None while not computable (warm-up, flat prices)."""
    logs = [math.log(c) for c in closes]
    out: list[Point | None] = [None] * len(closes)
    for i in range(window, len(closes)):
        rets = [logs[j] - logs[j - 1] for j in range(i - window + 1, i + 1)]
        mean = sum(rets) / window
        var = sum((r - mean) ** 2 for r in rets) / (window - 1)
        path = sum(abs(r) for r in rets)
        if var <= 0 or path <= 0:
            continue
        out[i] = (0.5 * math.log(var), abs(logs[i] - logs[i - window]) / path)
    return out


# --- Gaussian mixture (2-D, full covariance) ----------------------------------------------


@dataclass(frozen=True)
class Mixture:
    weights: tuple[float, ...]
    means: tuple[Point, ...]
    covs: tuple[Cov, ...]
    center: Point  # standardization of the training window
    scale: Point
    iterations: int

    def _log_densities(self, p: Point) -> list[float]:
        out = []
        for w, (mx, my), (a, b, c) in zip(self.weights, self.means, self.covs, strict=True):
            det = a * c - b * b
            dx, dy = p[0] - mx, p[1] - my
            quad = (c * dx * dx - 2 * b * dx * dy + a * dy * dy) / det
            out.append(math.log(w) - LOG_2PI - 0.5 * math.log(det) - 0.5 * quad)
        return out

    def standardize(self, raw: Point) -> Point:
        return ((raw[0] - self.center[0]) / self.scale[0],
                (raw[1] - self.center[1]) / self.scale[1])

    def label(self, raw: Point) -> int:
        dens = self._log_densities(self.standardize(raw))
        return max(range(len(dens)), key=dens.__getitem__)

    @property
    def trend_component(self) -> int:
        return max(range(len(self.means)), key=lambda k: self.means[k][1])


def _moments(points: Sequence[Point], resp: Sequence[float], reg: float
             ) -> tuple[float, Point, Cov]:
    n = sum(resp)
    mx = sum(r * p[0] for r, p in zip(resp, points, strict=True)) / n
    my = sum(r * p[1] for r, p in zip(resp, points, strict=True)) / n
    sxx = sum(r * (p[0] - mx) ** 2 for r, p in zip(resp, points, strict=True)) / n + reg
    syy = sum(r * (p[1] - my) ** 2 for r, p in zip(resp, points, strict=True)) / n + reg
    sxy = sum(r * (p[0] - mx) * (p[1] - my) for r, p in zip(resp, points, strict=True)) / n
    return n, (mx, my), (sxx, sxy, syy)


def _initial(points: Sequence[Point], k: int, reg: float
             ) -> tuple[tuple[float, ...], tuple[Point, ...], tuple[Cov, ...]]:
    """Deterministic start: sort by er, split into k equal groups."""
    order = sorted(range(len(points)), key=lambda i: (points[i][1], points[i][0]))
    size = len(points) / k
    means, covs = [], []
    for g in range(k):
        group = [points[i] for i in order[int(g * size):int((g + 1) * size)]]
        _, mean, cov = _moments(group, [1.0] * len(group), reg)
        means.append(mean)
        covs.append(cov)
    return tuple([1.0 / k] * k), tuple(means), tuple(covs)


def fit_mixture(raw: Sequence[Point], params: RegimeParams) -> Mixture:
    n = len(raw)
    if n < params.components * 10:
        raise ValueError("not enough points to fit the mixture")
    cx = sum(p[0] for p in raw) / n
    cy = sum(p[1] for p in raw) / n
    sx = math.sqrt(sum((p[0] - cx) ** 2 for p in raw) / n) or 1.0
    sy = math.sqrt(sum((p[1] - cy) ** 2 for p in raw) / n) or 1.0
    pts = [((p[0] - cx) / sx, (p[1] - cy) / sy) for p in raw]
    weights, means, covs = _initial(pts, params.components, params.reg)
    previous = -math.inf
    iterations = 0
    while iterations < params.max_iter:
        iterations += 1
        loglik, stats = _em_pass(pts, weights, means, covs)
        weights, means, covs = _m_step(stats, n, params.reg)
        if loglik - previous < params.tol:
            break
        previous = loglik
    return Mixture(weights, means, covs, (cx, cy), (sx, sy), iterations)


def _em_pass(pts: Sequence[Point], weights: Sequence[float], means: Sequence[Point],
             covs: Sequence[Cov]) -> tuple[float, list[list[float]]]:
    """One E-step fused with the sufficient statistics of the M-step.

    Returns the mean log-likelihood and, per component, [sum r, r*x, r*y, r*xx, r*xy, r*yy].
    """
    consts = []
    for w, (mx, my), (a, b, c) in zip(weights, means, covs, strict=True):
        det = a * c - b * b
        consts.append((math.log(w) - LOG_2PI - 0.5 * math.log(det), mx, my,
                       c / det, b / det, a / det))
    stats = [[0.0] * 6 for _ in consts]
    total = 0.0
    for x, y in pts:
        dens = []
        for k0, mx, my, ia, ib, ic in consts:
            dx, dy = x - mx, y - my
            dens.append(k0 - 0.5 * (ia * dx * dx - 2 * ib * dx * dy + ic * dy * dy))
        top = max(dens)
        norm = top + math.log(sum(math.exp(d - top) for d in dens))
        total += norm
        for st, d in zip(stats, dens, strict=True):
            # Floor keeps every component alive (no zero-weight division in the M-step).
            r = max(math.exp(d - norm), 1e-300)
            st[0] += r
            st[1] += r * x
            st[2] += r * y
            st[3] += r * x * x
            st[4] += r * x * y
            st[5] += r * y * y
    return total / len(pts), stats


def _m_step(stats: Sequence[Sequence[float]], n: int, reg: float
            ) -> tuple[tuple[float, ...], tuple[Point, ...], tuple[Cov, ...]]:
    weights, means, covs = [], [], []
    for r, rx, ry, rxx, rxy, ryy in stats:
        mx, my = rx / r, ry / r
        weights.append(r / n)
        means.append((mx, my))
        covs.append((max(rxx / r - mx * mx, 0.0) + reg, rxy / r - mx * my,
                     max(ryy / r - my * my, 0.0) + reg))
    return tuple(weights), tuple(means), tuple(covs)


# --- regime labels for an instrument ------------------------------------------------------


def refit_dates(first: datetime, last: datetime) -> list[datetime]:
    """1 January and 1 July (UTC) between `first` and `last`."""
    out = []
    for year in range(first.year, last.year + 1):
        for month in (1, 7):
            d = datetime(year, month, 1, tzinfo=UTC)
            if first <= d <= last:
                out.append(d)
    return out


def trend_flags(bars: Sequence[Bar], params: RegimeParams, active_from: datetime
                ) -> dict[datetime, bool]:
    """bar time -> True if labelled "trend". Bars without a fitted model are absent.

    Only refits whose period reaches `active_from` are computed (speed); a refit needs
    data covering its whole training window, otherwise it is skipped (ADR 0008).
    """
    if not bars:
        return {}
    feats = features([b.close for b in bars], params.feature_window)
    times = [b.time for b in bars]
    dates = refit_dates(times[0], times[-1])
    out: dict[datetime, bool] = {}
    for n, start in enumerate(dates):
        end = dates[n + 1] if n + 1 < len(dates) else times[-1] + timedelta(days=1)
        if end <= active_from:
            continue
        window_start = start.replace(year=start.year - params.train_years)
        if times[0] > window_start + START_TOLERANCE:
            continue  # incomplete training window
        train = [f for t, f in zip(times, feats, strict=True)
                 if f is not None and window_start <= t < start]
        model = fit_mixture(train, params)
        trend = model.trend_component
        for t, f in zip(times, feats, strict=True):
            if f is not None and start <= t < end:
                out[t] = model.label(f) == trend
    return out
