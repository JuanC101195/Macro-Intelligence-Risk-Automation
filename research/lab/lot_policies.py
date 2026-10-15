"""ADR 0015: replay trendbo-xau-h4-channel trades under lot policies between 0.01 and 0.05.

Informative study (not a hypothesis). Run from the main checkout:
    $env:PYTHONPATH = '<worktree>\\src'; python research/lab/lot_policies.py
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from trading_system.backtest import runner
from trading_system.backtest.engine import Backtest, BacktestConfig, ClosedTrade
from trading_system.backtest.financing import make_financing
from trading_system.backtest.trend_suite import _limits
from trading_system.backtest.walk_forward import add_months
from trading_system.domain import Timeframe
from trading_system.macro.fred_history import load
from trading_system.macro.rates import RateHistory
from trading_system.strategy.baseline import BaselineParams
from trading_system.strategy.trend_breakout import TrendBreakoutParams, TrendBreakoutStrategy

DATA = Path("research/datasets")
OZ_PER_LOT = 100.0
LEVERAGE = 50
RISK = 0.005
MIN_LOT, MAX_LOT = 0.01, 0.05
ACCOUNTS = {"standard": 1.0, "cent": 0.01}  # USD value of the standard-lot P&L
CAPITALS = (25.0, 100.0, 175.0)
SIGNAL_CAPITAL = 10_000_000.0  # large enough that no signal is rejected below 0.01 lots

Policy = Callable[[float, float, ClosedTrade, float], float]  # -> lot (0 = skip)


def _floor_lot(x: float) -> float:
    return math.floor(x * 100 + 1e-9) / 100


def fixed(lot: float) -> Policy:
    return lambda _eq, _start, _t, _scale: lot


def proportional(equity: float, _start: float, t: ClosedTrade, scale: float) -> float:
    risk_per_lot = t.risk_amount / t.volume * scale  # USD lost at the stop with 1.0 lot
    lot = min(_floor_lot(equity * RISK / risk_per_lot), MAX_LOT)
    return lot if lot >= MIN_LOT else 0.0


def steps(equity: float, start: float, _t: ClosedTrade, _scale: float) -> float:
    step = max(0, math.floor((equity / start - 1) / 0.5 + 1e-9))
    return min(MIN_LOT * (1 + step), MAX_LOT)


POLICIES: dict[str, Policy] = {"fijo-0.01": fixed(0.01), "fijo-0.05": fixed(0.05),
                               "proporcional": proportional, "escalones": steps}


def replay(trades: Sequence[ClosedTrade], policy: Policy, start: float, scale: float
           ) -> dict[str, float | int | bool]:
    equity, peak, max_dd, worst, skipped, ruined = start, start, 0.0, 0.0, 0, False
    for t in trades:
        margin_min = MIN_LOT * OZ_PER_LOT * t.entry_price / LEVERAGE * scale
        if equity <= 0 or equity < margin_min:
            ruined = True
            break
        lot = policy(equity, start, t, scale)
        if lot <= 0:
            skipped += 1
            continue
        pnl = t.pnl / t.volume * lot * scale
        worst = min(worst, pnl / equity)
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    return {"final": round(max(equity, 0.0), 2), "return_pct": round((equity / start - 1) * 100, 1),
            "max_dd_pct": round(max_dd * 100, 1), "worst_trade_pct": round(worst * 100, 1),
            "skipped": skipped, "ruined": ruined or equity <= 0}


def all_trades() -> tuple[list[ClosedTrade], datetime]:
    bars, hashes = runner.load_datasets(DATA, ["XAUUSD"], Timeframe.H4)
    s = TrendBreakoutStrategy(TrendBreakoutParams(timeframe=Timeframe.H4), bars)
    series = bars["XAUUSD"]
    cfg = BacktestConfig(symbols=("XAUUSD",), start=series[0].time,
                         end=add_months(series[-1].time, 1), limits=_limits(),
                         initial_equity=SIGNAL_CAPITAL, data_hashes=hashes, label="lot-study",
                         strategy=BaselineParams(timeframe=Timeframe.H4,
                                                 version="trendbo-xau-h4-channel"))
    result = Backtest(cfg, bars, decider=s.decide, exit_check=s.exit_check,
                      stop_update=s.stop_update, snapshots=False,
                      financing=make_financing(RateHistory(load(DATA / "fred_rates.json")))
                      ).run()
    return result.trades, runner.holdout_start(bars)


def main() -> None:
    trades, cut = all_trades()
    periods = {"2004-2026": trades,
               "2019-2026": [t for t in trades if t.entry_time >= datetime(2019, 1, 1, tzinfo=UTC)],
               "ultimos-12m": [t for t in trades if t.entry_time >= cut]}
    print("| Cuenta | Capital | Periodo | Politica | Final | Retorno % | DD max % | Peor op % "
          "| Saltadas | Ruina |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for account, scale in ACCOUNTS.items():
        for capital in CAPITALS:
            for period, subset in periods.items():
                for name, policy in POLICIES.items():
                    r = replay(subset, policy, capital, scale)
                    print(f"| {account} | {capital:g} | {period} ({len(subset)}) | {name} | "
                          f"{r['final']} | {r['return_pct']} | {r['max_dd_pct']} | "
                          f"{r['worst_trade_pct']} | {r['skipped']} | "
                          f"{'SI' if r['ruined'] else 'no'} |")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
