"""fibsr-xau-v002 with walk-forward optimization over 12 fixed variants (ADR 0011, 0012)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from trading_system.backtest import runner, wfo
from trading_system.backtest.engine import Backtest, BacktestConfig, ClosedTrade
from trading_system.backtest.financing import make_financing
from trading_system.backtest.walk_forward import add_months, rolling_windows
from trading_system.broker.contracts import Bar
from trading_system.domain import Timeframe
from trading_system.macro.rates import RateHistory
from trading_system.risk.contracts import RiskLimits
from trading_system.strategy.baseline import BaselineParams
from trading_system.strategy.fib_sr import FibSrParams, FibSrStrategy

SYMBOL = "XAUUSD"
VERSION = "fibsr-xau-v002"
WARMUP_MONTHS = 6  # data from 2015-07, decisions from 2016-01 (ADR 0011 addendum)
OOS_START = datetime(2019, 1, 1, tzinfo=UTC)
TEST_MONTHS = 6
TRAIN_MONTHS = 36
MIN_TRAIN_TRADES = 30
NULL_WORKERS = 4  # ~1 GB of M5 bars per worker
CAPITAL = 17_500.0  # cent-account equivalent (ADR 0005)

# ADR 0012 section 2, in table order (also the tie-break order).
VARIANTS: dict[str, dict[str, Any]] = {
    f"zz{zz:g}-leg{leg:g}-m5{'Y' if m5 else 'N'}-sr{'Y' if sr else 'N'}": {
        "zigzag_atr": zz, "min_leg_atr": leg, "m5_trend_required": m5, "sr_required": sr}
    for zz, leg in ((1.0, 2.0), (2.0, 4.0), (4.0, 10.0))
    for m5 in (True, False)
    for sr in (True, False)
}
# A9: the same procedure with other selection settings.
SELECTION_NEIGHBOURS: dict[str, tuple[int, wfo.Metric]] = {
    "train=24m": (24, "expectancy_r"),
    "train=48m": (48, "expectancy_r"),
    "select=profit_factor": (TRAIN_MONTHS, "profit_factor"),
}


def _limits() -> RiskLimits:
    # One gold position; spread/slippage limits off like ADR 0006 (fixed modelled costs).
    return RiskLimits(max_risk_per_trade=0.0025, max_daily_loss=0.02, max_open_positions=1,
                      max_consecutive_losses=5, max_spread_points=1_000_000,
                      max_slippage_points=1_000_000, max_trades_per_day=10)


def fixed_lot(trades: Sequence[ClosedTrade], lot: float = 0.01) -> dict[str, float]:
    """The same trades at a fixed lot (the partner's habit), informative only."""
    pnls = [t.pnl * lot / t.volume for t in trades if t.volume]
    curve, peak, worst_dd = 0.0, 0.0, 0.0
    for p in pnls:
        curve += p
        peak = max(peak, curve)
        worst_dd = max(worst_dd, peak - curve)
    return {"trades": len(pnls), "net_usd": round(curve, 2),
            "max_drawdown_usd": round(worst_dd, 2),
            "worst_trade_usd": round(min(pnls, default=0.0), 2)}


def run_fibsr_suite(
    m5: Sequence[Bar],
    h1: Sequence[Bar],
    hashes: Mapping[str, str],
    rates: RateHistory,
    *,
    neighbours: bool = True,
    null_runs: int = 0,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    bars = {SYMBOL: list(m5)}
    financing = make_financing(rates)
    strategies: dict[str, FibSrStrategy] = {}
    for name, change in VARIANTS.items():
        progress(f"preparing {name}")
        strategies[name] = FibSrStrategy(FibSrParams(**change), bars, {SYMBOL: list(h1)})
    any_strategy = next(iter(strategies.values()))  # stop management is the same for all

    first = m5[0].time
    cut = runner.holdout_start(bars)
    full_cfg = BacktestConfig(
        symbols=(SYMBOL,), start=add_months(first, WARMUP_MONTHS), end=cut, limits=_limits(),
        initial_equity=CAPITAL, data_hashes=dict(hashes), label="wfo-variant",
        strategy=BaselineParams(timeframe=Timeframe.M5, version=VERSION))
    variant_trades: dict[str, list[ClosedTrade]] = {}
    for name, s in strategies.items():
        progress(f"variant run {name}")
        variant_trades[name] = Backtest(full_cfg, bars, decider=s.decide,
                                        stop_update=s.stop_update, snapshots=False,
                                        financing=financing).run().trades

    windows = rolling_windows(OOS_START, cut, TEST_MONTHS)
    chosen = wfo.schedule(variant_trades, windows, TRAIN_MONTHS, "expectancy_r",
                          MIN_TRAIN_TRADES)
    alternatives = {name: wfo.schedule(variant_trades, windows, months, metric,
                                       MIN_TRAIN_TRADES)
                    for name, (months, metric) in SELECTION_NEIGHBOURS.items()}
    deciders = {name: s.decide for name, s in strategies.items()}
    built: list[Backtest] = []

    def build(cfg: BacktestConfig, variant: list[wfo.Window] | None) -> Backtest:
        bt = Backtest(cfg, bars, decider=wfo.Switching(deciders, variant or chosen),
                      stop_update=any_strategy.stop_update, snapshots=False,
                      financing=financing)
        built.append(bt)
        return bt

    offset = (OOS_START.year - first.year) * 12 + OOS_START.month - first.month
    result = runner.evaluate_suite(
        bars, hashes,
        strategy_cfg=BaselineParams(timeframe=Timeframe.M5, version=VERSION),
        strategy_info={"version": VERSION, "variants": VARIANTS,
                       "train_months": TRAIN_MONTHS, "test_months": TEST_MONTHS,
                       "selection": "expectancy_r", "min_train_trades": MIN_TRAIN_TRADES,
                       "base": FibSrParams().model_dump(mode="json")},
        build=build, variants=alternatives, limits=_limits(), initial_equity=CAPITAL,
        start_offset_months=offset,
        assumptions=("capital 17,500 = cent-account equivalent of ~700,000 COP (ADR 0005)",
                     "walk-forward: variant chosen on the previous 36 months of its own "
                     "continuous run, applied to the next 6 months (ADR 0012)",
                     "H1 context only from closed H1 bars; M5 decisions at the bar close",
                     "financing, spreads and slippage for XAUUSD as ADR 0006",
                     "orders fill at the next bar open; fills across data gaps are cancelled",
                     "breaker reset by a simulated operator at the next 17:00 New York"),
        neighbours=neighbours, null_runs=null_runs, null_workers=NULL_WORKERS,
        progress=progress)
    base_trades = built[0].trades  # the first build is the costs x1 base run
    result["walk_forward_selection"] = [
        {**asdict(w), "start": w.start.isoformat(), "end": w.end.isoformat()} for w in chosen]
    result["variant_trades"] = {name: len(t) for name, t in variant_trades.items()}
    result["fixed_lot_0_01"] = fixed_lot(base_trades)
    return result
