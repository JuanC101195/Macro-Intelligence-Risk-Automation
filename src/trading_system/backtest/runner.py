"""Research run of baseline-v001 against ADR 0002 Gate A.

- Data: latest Parquet per symbol in research/datasets (sha256 recorded).
- The last HOLDOUT_MONTHS are excluded from research runs by code (ADR 0002 rule 2).
  `holdout=True` evaluates ONLY that period, once, and records the claim.
- Suite: costs x1 (base), x1.5, x2; 6-month walk-forward windows; neighbouring
  parameter variants for stability (A9), fixed before any result was seen.
- Every run is appended to research/experiments.jsonl (ADR 0002 rule 3).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_system.backtest import gates
from trading_system.backtest.costs import CostModel
from trading_system.backtest.engine import Backtest, BacktestConfig
from trading_system.backtest.financing import make_financing
from trading_system.backtest.metrics import compute
from trading_system.backtest.pairs_engine import PairBacktest
from trading_system.backtest.walk_forward import add_months, rolling_windows, window_results
from trading_system.broker.contracts import Bar
from trading_system.broker.history import file_sha256, read_bars
from trading_system.domain import Timeframe
from trading_system.macro.macro_context import MacroContext
from trading_system.macro.rates import RateHistory
from trading_system.risk.contracts import RiskLimits
from trading_system.strategy.baseline import BaselineParams
from trading_system.strategy.breakout import BreakoutParams, BreakoutStrategy
from trading_system.strategy.carry import CarryParams, CarryStrategy
from trading_system.strategy.pairs import PairsParams, PairsStrategy
from trading_system.strategy.regimes import RegimeParams, trend_flags

WINDOW_MONTHS = 6

# A9 neighbours of baseline-v001, fixed in code before the first research run.
NEIGHBOURS: dict[str, dict[str, Any]] = {
    "adx_min=18": {"adx_min": 18.0},
    "adx_min=22": {"adx_min": 22.0},
    "sl_atr=1.25": {"sl_atr_mult": 1.25},
    "sl_atr=1.75": {"sl_atr_mult": 1.75},
    "rsi=38/62": {"rsi_pullback_long": 38.0, "rsi_pullback_short": 62.0},
    "rsi=42/58": {"rsi_pullback_long": 42.0, "rsi_pullback_short": 58.0},
}


def load_datasets(directory: Path, symbols: Sequence[str], timeframe: Timeframe = Timeframe.M15
                  ) -> tuple[dict[str, list[Bar]], dict[str, str]]:
    bars: dict[str, list[Bar]] = {}
    hashes: dict[str, str] = {}
    for sym in symbols:
        files = sorted(directory.glob(f"{sym}_{timeframe.value}_*.parquet"))
        if not files:
            raise FileNotFoundError(f"no {timeframe.value} dataset for {sym} in {directory}")
        bars[sym] = read_bars(files[-1])
        hashes[sym] = file_sha256(files[-1])
    return bars, hashes


def holdout_start(bars: Mapping[str, Sequence[Bar]]) -> datetime:
    last = min(b[-1].time for b in bars.values())
    return add_months(last, -gates.HOLDOUT_MONTHS)


def _limits() -> RiskLimits:
    return RiskLimits(max_risk_per_trade=0.0025, max_daily_loss=0.02, max_open_positions=1,
                      max_consecutive_losses=3, max_spread_points=30, max_slippage_points=10,
                      max_trades_per_day=5)


def _carry_limits() -> RiskLimits:
    # ADR 0004: up to 3 simultaneous positions (risk-policy ceiling), 10 trades/day,
    # 5 consecutive losses; everything else as the MVP defaults.
    return RiskLimits(max_risk_per_trade=0.0025, max_daily_loss=0.02, max_open_positions=3,
                      max_consecutive_losses=5, max_spread_points=30, max_slippage_points=10,
                      max_trades_per_day=10)


BuildBacktest = Callable[[BacktestConfig, Any], Backtest]


def evaluate_suite(
    bars: Mapping[str, Sequence[Bar]],
    hashes: Mapping[str, str],
    *,
    strategy_cfg: BaselineParams,
    strategy_info: Mapping[str, Any],
    build: BuildBacktest,
    variants: Mapping[str, Any],
    limits: RiskLimits,
    assumptions: Sequence[str],
    currency_exposure_mult: float = 1.0,
    initial_equity: float = 10_000.0,
    start_offset_months: int = 0,
    holdout: bool = False,
    neighbours: bool = True,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    """Costs x1/x1.5/x2, walk-forward, neighbour variants and Gate A for any strategy.

    `build(cfg, variant)` returns the Backtest to run; `variant` is None for the base run
    or one of `variants` (neighbours fixed before the run, ADR 0002 A9).
    """
    symbols = tuple(sorted(bars))
    cut = holdout_start(bars)
    first = max(b[0].time for b in bars.values())
    trade_from = add_months(first, start_offset_months)  # e.g. a model training window
    end = add_months(min(b[-1].time for b in bars.values()), 1) if holdout else cut
    start = cut if holdout else trade_from
    base_cfg = BacktestConfig(symbols=symbols, start=start, end=end, limits=limits,
                              strategy=strategy_cfg, data_hashes=dict(hashes),
                              currency_exposure_mult=currency_exposure_mult,
                              initial_equity=initial_equity,
                              label="holdout" if holdout else "research")

    def run(cfg: BacktestConfig, variant: Any, name: str) -> tuple[dict[str, Any], Any]:
        progress(name)
        result = build(cfg, variant).run()
        return compute(result), result

    base, base_result = run(base_cfg, None, "costs x1")
    costs15, _ = run(base_cfg.model_copy(update={"costs": CostModel().scaled(1.5)}), None,
                     "costs x1.5")
    costs20, _ = run(base_cfg.model_copy(update={"costs": CostModel().scaled(2.0)}), None,
                     "costs x2")
    windows = window_results(base_result.trades, rolling_windows(start, end, WINDOW_MONTHS))

    variant_exp: dict[str, float | None] = {}
    if neighbours and not holdout:
        for name, variant in variants.items():
            m, _ = run(base_cfg, variant, name)
            variant_exp[name] = m["expectancy"]

    history_years = (cut - trade_from).days / 365.25
    checks = gates.gate_a(history_years, base, costs15, windows,
                          neighbors=variant_exp or None,
                          holdout=base if holdout else None)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "label": base_cfg.label,
        "config_fingerprint": base_cfg.fingerprint(),
        "trades_digest": base_result.digest(),
        "period": {"start": start.isoformat(), "end": end.isoformat(),
                   "holdout_start": cut.isoformat(), "history_years": history_years},
        "symbols": list(symbols),
        "data_hashes": dict(hashes),
        "costs": CostModel().model_dump(),
        "strategy": dict(strategy_info),
        "metrics": {"costs_x1": base, "costs_x1.5": costs15, "costs_x2": costs20},
        "walk_forward": windows,
        "neighbours_expectancy": variant_exp,
        "gate_a": [asdict(c) for c in checks],
        "gate_a_passed": gates.gate_passed(checks),
        "assumptions": list(assumptions),
    }


_COMMON_ASSUMPTIONS = (
    "breaker reset by a simulated operator at the next 17:00 New York",
    "orders fill at the next bar open; fills across data gaps are cancelled",
)


def run_suite(
    bars: Mapping[str, Sequence[Bar]],
    hashes: Mapping[str, str],
    *,
    params: BaselineParams | None = None,
    macro: Callable[[datetime], MacroContext] | None = None,
    macro_source: str = "unknown (no history)",
    holdout: bool = False,
    neighbours: bool = True,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    """baseline-v001 family (ADR 0002 / 0003)."""
    params = params or BaselineParams()

    def build(cfg: BacktestConfig, variant: BaselineParams | None) -> Backtest:
        if variant is not None:
            cfg = cfg.model_copy(update={"strategy": variant})
        return Backtest(cfg, bars, macro=macro)

    # Neighbours inherit timeframe/version/filters from the hypothesis under test.
    variants = {name: params.model_copy(update=change) for name, change in NEIGHBOURS.items()}
    return evaluate_suite(
        bars, hashes, strategy_cfg=params, strategy_info=params.model_dump(mode="json"),
        build=build, variants=variants, limits=_limits(),
        assumptions=(f"macro context: {macro_source}",
                     "fixed retail spreads, 2 points slippage on entries and stops, no swap",
                     *_COMMON_ASSUMPTIONS),
        holdout=holdout, neighbours=neighbours, progress=progress,
    )


CARRY_NEIGHBOURS: dict[str, dict[str, Any]] = {
    "threshold=0.25": {"threshold": 0.25},
    "threshold=1.00": {"threshold": 1.00},
    "stop_atr=2": {"stop_atr": 2.0},
    "stop_atr=4": {"stop_atr": 4.0},
    "weekly": {"rebalance": "weekly"},
    "max_positions=2": {"max_positions": 2},
}


def run_carry_suite(
    bars: Mapping[str, Sequence[Bar]],
    hashes: Mapping[str, str],
    rates: RateHistory,
    *,
    params: CarryParams | None = None,
    holdout: bool = False,
    neighbours: bool = True,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    """carry-v001 (ADR 0004)."""
    params = params or CarryParams()

    def build(cfg: BacktestConfig, variant: CarryParams | None) -> Backtest:
        strategy = CarryStrategy(variant or params, rates, bars)
        return Backtest(cfg, bars, decider=strategy.decide, exit_check=strategy.exit_check,
                        financing=strategy.financing)

    variants = {n: params.model_copy(update=c) for n, c in CARRY_NEIGHBOURS.items()}
    return evaluate_suite(
        bars, hashes,
        strategy_cfg=BaselineParams(timeframe=Timeframe.D1, version=params.version),
        strategy_info=params.model_dump(mode="json"), build=build, variants=variants,
        limits=_carry_limits(), currency_exposure_mult=3.0,
        # ADR 0004 addendum: 10k cannot size D1 stops above the 0.01-lot minimum.
        initial_equity=100_000.0,
        assumptions=("FRED 3-month interbank rates, month M usable from day 1 of M+2",
                     f"swap = rate differential - {params.swap_markup}% per year, daily",
                     "fixed retail spreads, 2 points slippage on entries and all exits",
                     *_COMMON_ASSUMPTIONS),
        holdout=holdout, neighbours=neighbours, progress=progress,
    )


BREAKOUT_NEIGHBOURS: dict[str, dict[str, Any]] = {
    "entry=40": {"entry_window": 40},
    "entry=70": {"entry_window": 70},
    "exit=15": {"exit_window": 15},
    "exit=30": {"exit_window": 30},
    "stop_atr=1.5": {"stop_atr": 1.5},
    "stop_atr=2.5": {"stop_atr": 2.5},
}


def _breakout_limits() -> RiskLimits:
    # ADR 0006: 3 positions, spread limit off (fixed spreads of very different scale),
    # 10 trades/day, 5 consecutive losses.
    return RiskLimits(max_risk_per_trade=0.0025, max_daily_loss=0.02, max_open_positions=3,
                      max_consecutive_losses=5, max_spread_points=1_000_000,
                      max_slippage_points=1_000_000, max_trades_per_day=10)


def run_breakout_suite(
    bars: Mapping[str, Sequence[Bar]],
    hashes: Mapping[str, str],
    rates: RateHistory,
    *,
    params: BreakoutParams | None = None,
    neighbours: bool = True,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    """breakout-v001 (ADR 0006) on a cent-equivalent account (ADR 0005)."""
    params = params or BreakoutParams()
    financing = make_financing(rates)

    def build(cfg: BacktestConfig, variant: BreakoutParams | None) -> Backtest:
        strategy = BreakoutStrategy(variant or params, bars)
        return Backtest(cfg, bars, decider=strategy.decide, exit_check=strategy.exit_check,
                        financing=financing)

    variants = {n: params.model_copy(update=c) for n, c in BREAKOUT_NEIGHBOURS.items()}
    return evaluate_suite(
        bars, hashes,
        strategy_cfg=BaselineParams(timeframe=Timeframe.D1, version=params.version),
        strategy_info=params.model_dump(mode="json"), build=build, variants=variants,
        limits=_breakout_limits(), initial_equity=17_500.0,
        assumptions=("capital 17,500 = cent-account equivalent of ~700,000 COP (ADR 0005)",
                     "financing: FX rate differential - 1%; metals/indices long pays USD "
                     "rate + 1%, short pays 1%",
                     "fixed spreads and slippage per instrument (ADR 0006)",
                     "currency exposure checked only for 6-letter symbols, at 1x risk",
                     *_COMMON_ASSUMPTIONS),
        neighbours=neighbours, progress=progress,
    )


PAIRS_NEIGHBOURS: dict[str, dict[str, Any]] = {
    "entry_z=1.5": {"entry_z": 1.5},
    "entry_z=2.5": {"entry_z": 2.5},
    "z_window=120": {"z_window": 120},
    "z_window=480": {"z_window": 480},
    "beta_window=500": {"beta_window": 500},
    "beta_window=2000": {"beta_window": 2_000},
    "no_coint_filter": {"coint_filter": False},
}


def run_pairs_suite(
    bars: Mapping[str, Sequence[Bar]],
    hashes: Mapping[str, str],
    rates: RateHistory,
    *,
    params: PairsParams | None = None,
    neighbours: bool = True,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    """pairs-v001 (ADR 0007) on H1, cent-equivalent capital (ADR 0005)."""
    params = params or PairsParams()
    financing = make_financing(rates)
    strategies: dict[str, PairsStrategy] = {}  # the cost runs reuse the base precomputation

    def build(cfg: BacktestConfig, variant: PairsParams | None) -> Backtest:
        chosen = variant or params
        key = chosen.model_dump_json()
        if key not in strategies:
            strategies[key] = PairsStrategy(chosen, bars)
        return PairBacktest(cfg, bars, strategies[key], financing=financing)

    variants = {n: params.model_copy(update=c) for n, c in PAIRS_NEIGHBOURS.items()}
    return evaluate_suite(
        bars, hashes,
        strategy_cfg=BaselineParams(timeframe=Timeframe.H1, version=params.version),
        strategy_info=params.model_dump(mode="json"), build=build, variants=variants,
        limits=_carry_limits(), initial_equity=17_500.0,
        assumptions=("capital 17,500 = cent-account equivalent of ~700,000 COP (ADR 0005)",
                     "one trade = one complete pair (both legs), net P&L",
                     "financing per leg: FX rate differential - 1% per year",
                     "fixed retail spreads and 2 points slippage on every leg fill",
                     *_COMMON_ASSUMPTIONS),
        neighbours=neighbours, progress=progress,
    )


REGIME_NEIGHBOURS: dict[str, dict[str, Any]] = {
    "components=2": {"components": 2},
    "components=4": {"components": 4},
    "feature_window=20": {"feature_window": 20},
    "feature_window=50": {"feature_window": 50},
    "train_years=1": {"train_years": 1},
    "train_years=3": {"train_years": 3},
}
REGIME_TRAIN_MONTHS = 24  # ADR 0008: trade only after the base training window


def _flags_for(args: tuple[str, Sequence[Bar], RegimeParams, datetime]
               ) -> tuple[str, dict[datetime, bool]]:
    sym, series, params, active_from = args
    return sym, trend_flags(series, params, active_from)


def regime_flags(bars: Mapping[str, Sequence[Bar]], params: RegimeParams,
                 active_from: datetime) -> dict[str, dict[datetime, bool]]:
    """Per-instrument fits are independent: computed in parallel, results are identical."""
    jobs = [(sym, bars[sym], params, active_from) for sym in sorted(bars)]
    with ProcessPoolExecutor() as pool:
        return dict(pool.map(_flags_for, jobs))


def run_regime_suite(
    bars: Mapping[str, Sequence[Bar]],
    hashes: Mapping[str, str],
    rates: RateHistory,
    *,
    control: bool = False,
    regime: RegimeParams | None = None,
    neighbours: bool = True,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    """regime-h4-v001, or its unfiltered control breakout-h4-v001 (ADR 0008)."""
    version = "breakout-h4-v001" if control else "regime-h4-v001"
    params = BreakoutParams(version=version, timeframe=Timeframe.H4)
    regime = regime or RegimeParams()
    financing = make_financing(rates)
    first = max(b[0].time for b in bars.values())
    active_from = add_months(first, REGIME_TRAIN_MONTHS)
    flags: dict[str, dict[str, dict[datetime, bool]]] = {}

    def build(cfg: BacktestConfig, variant: Any) -> Backtest:
        if control:
            strategy = BreakoutStrategy(variant or params, bars)
        else:
            chosen = variant or regime
            key = chosen.model_dump_json()
            if key not in flags:
                progress(f"fitting regimes {key}")
                flags[key] = regime_flags(bars, chosen, active_from)
            strategy = BreakoutStrategy(params, bars, regime=flags[key])
        return Backtest(cfg, bars, decider=strategy.decide, exit_check=strategy.exit_check,
                        financing=financing)

    if control:
        variants: dict[str, Any] = {n: params.model_copy(update=c)
                                    for n, c in BREAKOUT_NEIGHBOURS.items()}
        info = params.model_dump(mode="json")
    else:
        variants = {n: regime.model_copy(update=c) for n, c in REGIME_NEIGHBOURS.items()}
        info = {**params.model_dump(mode="json"), "regime": regime.model_dump(mode="json")}
    return evaluate_suite(
        bars, hashes,
        strategy_cfg=BaselineParams(timeframe=Timeframe.H4, version=version),
        strategy_info=info, build=build, variants=variants,
        limits=_breakout_limits(), initial_equity=17_500.0,
        start_offset_months=REGIME_TRAIN_MONTHS,
        assumptions=("capital 17,500 = cent-account equivalent of ~700,000 COP (ADR 0005)",
                     "breakout rules of ADR 0006 counted in H4 bars",
                     "regime filter: per-instrument GMM refitted every 6 months on the "
                     "previous years only" if not control else "no regime filter (control)",
                     "financing, spreads and slippage as ADR 0006",
                     *_COMMON_ASSUMPTIONS),
        neighbours=neighbours, progress=progress,
    )


def log_experiment(report: Mapping[str, Any], log_path: Path) -> None:
    m = report["metrics"]["costs_x1"]
    line = {
        "at": report["generated_at"], "label": report["label"],
        "config": report["config_fingerprint"], "digest": report["trades_digest"],
        "strategy": report["strategy"]["version"], "trades": m["trades"],
        "net": m["net_profit"], "pf": m["profit_factor"], "expectancy": m["expectancy"],
        "gate_a_passed": report["gate_a_passed"],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, default=str) + "\n")
