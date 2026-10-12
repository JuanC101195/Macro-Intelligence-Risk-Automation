"""ADR 0009, prueba 2: the GMM regime filter against 200 random filters (pre-registered).

Null filter: per instrument and bar, "trend" at random with the same probability as the
share of trend bars the GMM gave that instrument, only on bars where the GMM had a model.
Each filter runs on OUR engine with the base configuration of regime-h4-v001 (costs x1).
Criterion: the GMM filter carries information if its profit factor exceeds the 95th
percentile of the random filters.
  .venv-research\\Scripts\\python.exe research\\lab\\null_regime.py
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from trading_system.backtest.engine import Backtest, BacktestConfig
from trading_system.backtest.financing import make_financing
from trading_system.backtest.metrics import compute
from trading_system.backtest.runner import (
    REGIME_TRAIN_MONTHS,
    _breakout_limits,
    holdout_start,
    load_datasets,
    regime_flags,
)
from trading_system.backtest.walk_forward import add_months
from trading_system.broker.contracts import Bar
from trading_system.cli import _load_rates
from trading_system.domain import Timeframe
from trading_system.strategy.baseline import BaselineParams
from trading_system.strategy.breakout import BreakoutParams, BreakoutStrategy
from trading_system.strategy.regimes import RegimeParams

DATA = Path("research/datasets")
OUT = Path("research/reports/null_regime.json")  # local only (ADR 0001 #14)
SYMBOLS = ("XAUUSD", "XAGUSD", "US500", "US30", "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD",
           "USDJPY", "USDCAD", "USDCHF")
SEEDS = range(200)
PARAMS = BreakoutParams(version="regime-h4-v001", timeframe=Timeframe.H4)

_STATE: dict[str, Any] = {}


def _init(bars: dict[str, list[Bar]], cfg: BacktestConfig) -> None:
    _STATE["bars"] = bars
    _STATE["cfg"] = cfg
    _STATE["financing"] = make_financing(_load_rates(DATA))


def run(flags: dict[str, dict[datetime, bool]]) -> dict[str, float]:
    bars, cfg = _STATE["bars"], _STATE["cfg"]
    strategy = BreakoutStrategy(PARAMS, bars, regime=flags)
    result = Backtest(cfg, bars, decider=strategy.decide, exit_check=strategy.exit_check,
                      financing=_STATE["financing"]).run()
    m = compute(result)
    return {"trades": m["trades"], "pf": m["profit_factor"], "expectancy": m["expectancy"],
            "dd": m["max_drawdown_pct"]}


def random_flags(gmm: dict[str, dict[datetime, bool]], seed: int
                 ) -> dict[str, dict[datetime, bool]]:
    rng = np.random.default_rng(seed)
    out = {}
    for sym in sorted(gmm):
        times = sorted(gmm[sym])
        share = sum(gmm[sym].values()) / len(times)
        draws = rng.random(len(times)) < share
        out[sym] = dict(zip(times, (bool(d) for d in draws), strict=True))
    return out


def _null(seed: int) -> dict[str, float]:
    return run(random_flags(_STATE["gmm"], seed))


def _init_null(bars: dict[str, list[Bar]], cfg: BacktestConfig,
               gmm: dict[str, dict[datetime, bool]]) -> None:
    _init(bars, cfg)
    _STATE["gmm"] = gmm


def percentile(value: float, sample: list[float]) -> float:
    return sum(v < value for v in sample) / len(sample)


def main() -> int:
    bars, hashes = load_datasets(DATA, list(SYMBOLS), Timeframe.H4)
    first = max(b[0].time for b in bars.values())
    start = add_months(first, REGIME_TRAIN_MONTHS)
    cfg = BacktestConfig(symbols=tuple(sorted(bars)), start=start, end=holdout_start(bars),
                         limits=_breakout_limits(), initial_equity=17_500.0,
                         data_hashes=dict(hashes), label="null-regime",
                         strategy=BaselineParams(timeframe=Timeframe.H4, version=PARAMS.version))
    gmm = regime_flags(bars, RegimeParams(), start)
    _init(bars, cfg)
    observed = run(gmm)
    print("GMM filter:", observed)
    with ProcessPoolExecutor(initializer=_init_null, initargs=(bars, cfg, gmm)) as pool:
        null = list(pool.map(_null, SEEDS))
    pfs = [n["pf"] for n in null]
    p95 = float(np.percentile(pfs, 95))
    summary = {
        "observed": observed,
        "null_pf": {"p5": float(np.percentile(pfs, 5)), "median": float(np.median(pfs)),
                    "p95": p95},
        "percentile": {k: percentile(observed[k], [n[k] for n in null])
                       for k in ("pf", "expectancy", "dd")},
        "p_value_pf": (1 + sum(v >= observed["pf"] for v in pfs)) / (len(pfs) + 1),
        "passes": observed["pf"] > p95,
        "null_trades": {"min": min(n["trades"] for n in null),
                        "max": max(n["trades"] for n in null)},
    }
    OUT.write_text(json.dumps({**summary, "null": null}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
