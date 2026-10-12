"""ADR 0009, prueba 1: the pure-Python GMM (ADR 0008) against scikit-learn.

Same standardized points, same deterministic initialization, same tol/reg_covar/max_iter.
Run with the research venv:  .venv-research\\Scripts\\python.exe research\\lab\\gmm_vs_sklearn.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sklearn.mixture import GaussianMixture

from trading_system.backtest.runner import load_datasets
from trading_system.domain import Timeframe
from trading_system.strategy.regimes import RegimeParams, _initial, features, fit_mixture

DATA = Path("research/datasets")
TOLERANCE = 1e-4


def compare(symbol: str, start: datetime, end: datetime, params: RegimeParams) -> float:
    bars, _ = load_datasets(DATA, [symbol], Timeframe.H4)
    series = bars[symbol]
    feats = features([b.close for b in series], params.feature_window)
    raw = [f for f, b in zip(feats, series, strict=True) if f and start <= b.time < end]
    ours = fit_mixture(raw, params)

    pts = np.array([ours.standardize(p) for p in raw])
    weights, means, covs = _initial([tuple(p) for p in pts], params.components, params.reg)
    precisions = [np.linalg.inv(np.array([[a, b], [b, c]])) for a, b, c in covs]
    sk = GaussianMixture(
        n_components=params.components, covariance_type="full", tol=params.tol,
        reg_covar=params.reg, max_iter=params.max_iter, weights_init=np.array(weights),
        means_init=np.array(means), precisions_init=np.array(precisions),
        random_state=0,  # unused with explicit init; fixed for reproducibility
    ).fit(pts)

    # Same component order: both start from the same initialization.
    diff = max(
        float(np.max(np.abs(np.array(ours.means) - sk.means_))),
        float(np.max(np.abs(np.array(ours.weights) - sk.weights_))),
    )
    print(f"{symbol} {start:%Y-%m}..{end:%Y-%m} n={len(raw)} K={params.components} "
          f"iters ours={ours.iterations} sklearn={sk.n_iter_} max|diff|={diff:.2e}")
    return diff


def main() -> int:
    cases = [
        ("EURUSD", datetime(2012, 7, 1, tzinfo=UTC), datetime(2014, 7, 1, tzinfo=UTC), 3),
        ("XAUUSD", datetime(2018, 1, 1, tzinfo=UTC), datetime(2020, 1, 1, tzinfo=UTC), 3),
        ("US500", datetime(2020, 7, 1, tzinfo=UTC), datetime(2022, 7, 1, tzinfo=UTC), 4),
    ]
    worst = max(compare(s, a, b, RegimeParams(components=k)) for s, a, b, k in cases)
    ok = worst < TOLERANCE
    print("PASS" if ok else "FAIL", f"worst={worst:.2e} tolerance={TOLERANCE}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
