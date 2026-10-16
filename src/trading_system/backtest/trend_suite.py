"""trendbo-xau-v001 (ADR 0014): EMA 50/200 + 20-bar breakout on gold, one version per run."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from statistics import median
from typing import Any

from trading_system.backtest import runner
from trading_system.backtest.engine import Backtest, BacktestConfig, ClosedTrade
from trading_system.backtest.fibsr_suite import fixed_lot
from trading_system.backtest.financing import make_financing
from trading_system.broker.contracts import Bar
from trading_system.domain import Timeframe
from trading_system.macro.rates import RateHistory
from trading_system.risk.contracts import RiskLimits
from trading_system.strategy.baseline import BaselineParams
from trading_system.strategy.trend_breakout import (
    ExitMode,
    TrendBreakoutParams,
    TrendBreakoutStrategy,
)

SYMBOL = "XAUUSD"
CAPITAL = 17_500.0  # cent-account equivalent (ADR 0005)
TIMEFRAMES = (Timeframe.H1, Timeframe.H4, Timeframe.D1)  # H1 added by ADR 0019
# ADR 0019: the ADR 0006 universe, fixed before any run (all or nothing).
BASKET = ("XAUUSD", "XAGUSD", "US500", "US30", "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD",
          "USDJPY", "USDCAD", "USDCHF")

# A9 neighbours, fixed in ADR 0014 before any run.
NEIGHBOURS: dict[str, dict[str, Any]] = {
    "ema=40/160": {"ema_fast": 40, "ema_slow": 160},
    "ema=60/240": {"ema_fast": 60, "ema_slow": 240},
    "entry=15": {"entry_window": 15},
    "entry=25": {"entry_window": 25},
    "stop=1.5atr": {"stop_atr": 1.5},
    "stop=2.5atr": {"stop_atr": 2.5},
}


TARGET_RS = (2.0, 1.0)  # 2.0 = ADR 0014, 1.0 = ADR 0020 (1:1)
USD_PER_R = 10.0  # ADR 0020: "win 10 or lose 10" view of the same trades


def is_target_r(value: float, expected: float) -> bool:
    return math.isclose(value, expected, abs_tol=1e-9)


def preregistered_target_r(value: float) -> bool:
    return any(is_target_r(value, r) for r in TARGET_RS)


def version_name(timeframe: Timeframe, exit_mode: ExitMode, trend_filter: bool,
                 target_r: float = 2.0) -> str:
    if exit_mode == "target" and is_target_r(target_r, 1.0):
        name = f"trendbo-xau-{timeframe.value.lower()}-target1r"
    else:
        name = f"trendbo-xau-{timeframe.value.lower()}-{exit_mode}"
    return name if trend_filter else f"{name}-nofilter"


def r_dollar_stats(trades: Sequence[ClosedTrade], usd_per_r: float = USD_PER_R) -> dict[str, Any]:
    """The trades as if each one risked `usd_per_r` dollars (ADR 0020), informative."""
    if not trades:
        return {"trades": 0}
    weeks: dict[tuple[int, int], float] = {}
    months: dict[tuple[int, int], float] = {}
    run = worst_run = 0.0
    for t in sorted(trades, key=lambda x: x.exit_time):
        usd = t.r_multiple * usd_per_r
        iso = t.exit_time.isocalendar()
        weeks[(iso[0], iso[1])] = weeks.get((iso[0], iso[1]), 0.0) + usd
        key = (t.exit_time.year, t.exit_time.month)
        months[key] = months.get(key, 0.0) + usd
        run = min(run + usd, 0.0)
        worst_run = min(worst_run, run)
    first = min(t.entry_time for t in trades)
    last = max(t.exit_time for t in trades)
    n_weeks = max((last - first).days / 7, 1.0)
    wins = sum(t.pnl > 0 for t in trades)
    return {
        "usd_per_trade_risk": usd_per_r,
        "win_rate": round(wins / len(trades), 3),
        "net_usd": round(sum(weeks.values()), 2),
        "mean_week_usd": round(sum(weeks.values()) / n_weeks, 2),
        "worst_week_usd": round(min(weeks.values()), 2),
        "worst_month_usd": round(min(months.values()), 2),
        "worst_drawdown_usd": round(worst_run, 2),
    }


def _limits() -> RiskLimits:
    # ADR 0014: 0.5 % per trade, one gold position, spread/slippage limits off (fixed costs).
    return RiskLimits(max_risk_per_trade=0.005, max_daily_loss=0.02, max_open_positions=1,
                      max_consecutive_losses=5, max_spread_points=1_000_000,
                      max_slippage_points=1_000_000, max_trades_per_day=10)


def run_trend_suite(
    bars: Sequence[Bar],
    hashes: Mapping[str, str],
    rates: RateHistory,
    *,
    timeframe: Timeframe,
    exit_mode: ExitMode,
    trend_filter: bool = True,
    target_r: float = 2.0,
    holdout: bool = False,
    neighbours: bool = True,
    null_runs: int = 0,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    data = {SYMBOL: list(bars)}
    version = version_name(timeframe, exit_mode, trend_filter, target_r)
    params = TrendBreakoutParams(version=version, timeframe=timeframe, exit_mode=exit_mode,
                                 trend_filter=trend_filter, target_r=target_r)
    financing = make_financing(rates)
    built: list[Backtest] = []

    def build(cfg: BacktestConfig, variant: TrendBreakoutParams | None) -> Backtest:
        strategy = TrendBreakoutStrategy(variant or params, data)
        bt = Backtest(cfg, data, decider=strategy.decide, exit_check=strategy.exit_check,
                      stop_update=strategy.stop_update, financing=financing, snapshots=False)
        built.append(bt)
        return bt

    variants = {n: params.model_copy(update=c) for n, c in NEIGHBOURS.items()}
    result = runner.evaluate_suite(
        data, hashes,
        strategy_cfg=BaselineParams(timeframe=timeframe, version=version),
        strategy_info=params.model_dump(mode="json"), build=build, variants=variants,
        limits=_limits(), initial_equity=CAPITAL,
        assumptions=("capital 17,500 = cent-account equivalent of ~700,000 COP (ADR 0005)",
                     "risk 0.5 % per trade; below 0.01 lots the trade is rejected",
                     "financing, spreads and slippage for XAUUSD as ADR 0006",
                     "orders fill at the next bar open; fills across data gaps are cancelled",
                     "breaker reset by a simulated operator at the next 17:00 New York"),
        holdout=holdout, neighbours=neighbours, null_runs=null_runs, progress=progress)
    base = built[0]  # the first build is the costs x1 base run
    result["rejections"] = dict(base.rejections)
    result["hold_reasons"] = dict(base.holds)
    result["fixed_lot_0_01"] = fixed_lot(base.trades)
    result["weekly"] = weekly_stats(base.trades, CAPITAL)
    result["usd_per_r_view"] = r_dollar_stats(base.trades)
    return result


def _basket_limits() -> RiskLimits:
    # ADR 0019 = ADR 0006 limits: 0.25 % per trade, 3 positions, spread limit off.
    return RiskLimits(max_risk_per_trade=0.0025, max_daily_loss=0.02, max_open_positions=3,
                      max_consecutive_losses=5, max_spread_points=1_000_000,
                      max_slippage_points=1_000_000, max_trades_per_day=10)


def weekly_stats(trades: Sequence[ClosedTrade], capital: float) -> dict[str, Any]:
    """Trades and result per ISO week (by exit), informative (ADR 0019)."""
    if not trades:
        return {"weeks": 0}
    by_week: dict[tuple[int, int], list[float]] = {}
    for t in trades:
        iso = t.exit_time.isocalendar()
        by_week.setdefault((iso[0], iso[1]), []).append(t.pnl)
    first, last = min(t.entry_time for t in trades), max(t.exit_time for t in trades)
    n_weeks = max((last - first).days / 7, 1.0)
    results = [sum(v) / capital * 100 for v in by_week.values()]
    months: dict[tuple[int, int], float] = {}
    for t in trades:
        key = (t.exit_time.year, t.exit_time.month)
        months[key] = months.get(key, 0.0) + t.pnl
    return {
        "trades_per_week_mean": round(len(trades) / n_weeks, 2),
        "trades_per_week_median_active": median(len(v) for v in by_week.values()),
        "weeks_with_trades_pct": round(len(by_week) / n_weeks * 100, 1),
        "positive_weeks_pct": round(sum(r > 0 for r in results) / n_weeks * 100, 1),
        "mean_week_pct": round(sum(results) / n_weeks, 3),
        "worst_week_pct": round(min(results), 2),
        "worst_month_pct": round(min(months.values()) / capital * 100, 2),
    }


def run_trend_basket(
    bars: Mapping[str, Sequence[Bar]],
    hashes: Mapping[str, str],
    rates: RateHistory,
    *,
    neighbours: bool = True,
    null_runs: int = 0,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    """trendbo-basket-h4-channel (ADR 0019): frozen h4-channel rules on the ADR 0006 basket."""
    data = {s: list(b) for s, b in bars.items()}
    version = "trendbo-basket-h4-channel"
    params = TrendBreakoutParams(version=version, timeframe=Timeframe.H4, exit_mode="channel")
    financing = make_financing(rates)
    built: list[Backtest] = []

    def build(cfg: BacktestConfig, variant: TrendBreakoutParams | None) -> Backtest:
        strategy = TrendBreakoutStrategy(variant or params, data)
        bt = Backtest(cfg, data, decider=strategy.decide, exit_check=strategy.exit_check,
                      stop_update=strategy.stop_update, financing=financing, snapshots=False)
        built.append(bt)
        return bt

    variants = {n: params.model_copy(update=c) for n, c in NEIGHBOURS.items()}
    result = runner.evaluate_suite(
        data, hashes,
        strategy_cfg=BaselineParams(timeframe=Timeframe.H4, version=version),
        strategy_info=params.model_dump(mode="json"), build=build, variants=variants,
        limits=_basket_limits(), initial_equity=CAPITAL,
        assumptions=("capital 17,500 = cent-account equivalent of ~700,000 COP (ADR 0005)",
                     "risk 0.25 % per trade, max 3 positions, first come first served",
                     "fixed spreads, slippage and financing per instrument (ADR 0006)",
                     "all-or-nothing basket: no instrument may be dropped after the run",
                     "orders fill at the next bar open; fills across data gaps are cancelled"),
        neighbours=neighbours, null_runs=null_runs, progress=progress)
    base = built[0]
    result["rejections"] = dict(base.rejections)
    result["hold_reasons"] = dict(base.holds)
    result["weekly"] = weekly_stats(base.trades, CAPITAL)
    result["per_symbol_informative"] = _per_symbol(base.trades)
    return result


def _per_symbol(trades: Sequence[ClosedTrade]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for t in trades:
        row = out.setdefault(t.symbol, {"trades": 0, "net": 0.0, "gross_win": 0.0,
                                        "gross_loss": 0.0})
        row["trades"] += 1
        row["net"] += t.pnl
        row["gross_win" if t.pnl > 0 else "gross_loss"] += abs(t.pnl)
    for row in out.values():
        row["pf"] = round(row["gross_win"] / row["gross_loss"], 3) if row["gross_loss"] else 0.0
        row["net"] = round(row["net"], 2)
    return out
