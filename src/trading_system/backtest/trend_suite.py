"""trendbo-xau-v001 (ADR 0014): EMA 50/200 + 20-bar breakout on gold, one version per run."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from trading_system.backtest import runner
from trading_system.backtest.engine import Backtest, BacktestConfig
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
TIMEFRAMES = (Timeframe.H4, Timeframe.D1)

# A9 neighbours, fixed in ADR 0014 before any run.
NEIGHBOURS: dict[str, dict[str, Any]] = {
    "ema=40/160": {"ema_fast": 40, "ema_slow": 160},
    "ema=60/240": {"ema_fast": 60, "ema_slow": 240},
    "entry=15": {"entry_window": 15},
    "entry=25": {"entry_window": 25},
    "stop=1.5atr": {"stop_atr": 1.5},
    "stop=2.5atr": {"stop_atr": 2.5},
}


def version_name(timeframe: Timeframe, exit_mode: ExitMode, trend_filter: bool) -> str:
    name = f"trendbo-xau-{timeframe.value.lower()}-{exit_mode}"
    return name if trend_filter else f"{name}-nofilter"


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
    neighbours: bool = True,
    null_runs: int = 0,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    data = {SYMBOL: list(bars)}
    version = version_name(timeframe, exit_mode, trend_filter)
    params = TrendBreakoutParams(version=version, timeframe=timeframe, exit_mode=exit_mode,
                                 trend_filter=trend_filter)
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
        neighbours=neighbours, null_runs=null_runs, progress=progress)
    base = built[0]  # the first build is the costs x1 base run
    result["rejections"] = dict(base.rejections)
    result["hold_reasons"] = dict(base.holds)
    result["fixed_lot_0_01"] = fixed_lot(base.trades)
    return result
