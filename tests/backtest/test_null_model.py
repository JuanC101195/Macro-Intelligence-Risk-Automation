"""ADR 0010: random-entry null model behind Gate A criterion A11."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from tests.fixtures.bars import random_walk
from trading_system.backtest import gates, null_model, runner
from trading_system.backtest.engine import Backtest, BacktestConfig
from trading_system.domain import Timeframe
from trading_system.strategy.baseline import BaselineParams
from trading_system.strategy.breakout import BreakoutParams, BreakoutStrategy

PARAMS = BreakoutParams(version="breakout-test", entry_window=20, exit_window=10,
                        timeframe=Timeframe.M15)


def _setup() -> tuple[dict[str, Any], Backtest]:
    bars = {"EURUSD": random_walk(3000, seed=3), "GBPUSD": random_walk(3000, seed=4)}
    first = bars["EURUSD"][0].time
    cfg = BacktestConfig(symbols=("EURUSD", "GBPUSD"), start=first,
                         end=first + timedelta(days=60), limits=runner._breakout_limits(),
                         strategy=BaselineParams(timeframe=Timeframe.M15, version=PARAMS.version))
    strategy = BreakoutStrategy(PARAMS, bars)
    return bars, Backtest(cfg, bars, decider=strategy.decide, exit_check=strategy.exit_check)


def _recorded() -> tuple[Any, null_model.ProfileRecorder, Backtest]:
    bars, bt = _setup()
    recorder = null_model.ProfileRecorder(bt.decide, null_model.atr_by_bar(bars))
    bt.decide = recorder
    return bt.run(), recorder, _setup()[1]


def test_recorder_does_not_change_the_base_run() -> None:
    _, plain = _setup()
    recorded, recorder, _ = _recorded()
    assert recorded.digest() == plain.run().digest()
    prof = recorder.profile["EURUSD"]
    assert prof.entries > 0
    assert prof.flat_calls > prof.entries
    assert 0 < prof.long_share < 1
    assert all(stop > 0 and target > 0 for stop, target in prof.brackets)


def test_random_entries_are_reproducible_and_seed_dependent() -> None:
    _, recorder, template = _recorded()
    atr = recorder.atr
    first = null_model.run_seed(template, recorder.profile, atr, seed=1)
    again = null_model.run_seed(template, recorder.profile, atr, seed=1)
    other = null_model.run_seed(template, recorder.profile, atr, seed=2)
    assert first == again
    assert first["trades"] > 0
    assert (first["trades"], first["pf"]) != (other["trades"], other["pf"])


def test_random_entry_uses_observed_bracket_in_atr_units() -> None:
    bars, template = _setup()
    atr = null_model.atr_by_bar(bars)
    profile = {"EURUSD": null_model.SymbolProfile(flat_calls=1, longs=1, brackets=[(2.0, 5.0)])}
    seen: list[Any] = []
    decider = null_model.RandomEntries(template.decide, profile, atr, seed=0)

    def spy(*args: Any) -> Any:
        signal = decider(*args)
        if signal.side.value != "HOLD":
            seen.append((signal, atr[("EURUSD", signal.bar_time)]))
        return signal

    Backtest(template.cfg, bars, decider=spy, exit_check=template.exit_check).run()
    assert seen
    for signal, a in seen:
        assert signal.symbol == "EURUSD"  # no profile -> never enters GBPUSD
        assert signal.side.value == "LONG"
        assert signal.entry_ref - signal.stop_loss == pytest.approx(2.0 * a, abs=1e-5)
        assert signal.take_profit - signal.entry_ref == pytest.approx(5.0 * a, abs=1e-5)


def test_worker_processes_reproduce_the_in_process_run() -> None:
    _, recorder, template = _recorded()
    [remote] = null_model.run_null(template, recorder.profile, recorder.atr, [5], workers=1)
    assert remote == null_model.run_seed(template, recorder.profile, recorder.atr, seed=5)


def test_percentile_and_summary() -> None:
    assert null_model.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0
    assert null_model.percentile([float(i) for i in range(101)], 95) == pytest.approx(95.0)
    null = [{"trades": 10, "pf": 0.8 + i / 1000, "expectancy": -1.0, "dd": 0.1}
            for i in range(200)]
    observed = {"trades": 12, "profit_factor": 1.5, "expectancy": 2.0,
                "max_drawdown_pct": 0.05}
    s = null_model.summarize(observed, null, {})
    assert s["passes"]
    assert s["rank_pf"] == 1.0
    assert s["p_value_pf"] == pytest.approx(1 / 201)
    weak = null_model.summarize({**observed, "profit_factor": 0.95}, null, {})
    assert not weak["passes"]


def _metrics(**overrides: Any) -> dict[str, Any]:
    m: dict[str, Any] = {"trades": 400, "expectancy": 3.0, "profit_factor": 1.4,
                         "max_drawdown_pct": 0.06, "net_profit": 1200.0,
                         "by_year": {"2023": {"net": 500.0}}}
    m.update(overrides)
    return m


@pytest.mark.parametrize(("passes", "status"), [(True, "pass"), (False, "fail"), (None, "pending")])
def test_gate_a11(passes: bool | None, status: str) -> None:
    null = None if passes is None else {"passes": passes, "null_pf": {"p95": 1.1}}
    checks = {c.id: c for c in gates.gate_a(3.1, _metrics(), _metrics(), [], null=null)}
    assert checks["A11"].status == status


def test_suite_runs_the_null_model_and_fills_a11() -> None:
    bars = {"EURUSD": random_walk(1500, seed=3)}
    result = runner.run_suite(bars, {"EURUSD": "x"},
                              params=BaselineParams(timeframe=Timeframe.M15, version="t"),
                              neighbours=False, null_runs=2)
    a11 = next(c for c in result["gate_a"] if c["id"] == "A11")
    assert a11["status"] in ("pass", "fail")
    assert result["null_model"]["runs"] == 2


def test_suite_without_null_leaves_a11_pending() -> None:
    bars = {"EURUSD": random_walk(700)}
    result = runner.run_suite(bars, {"EURUSD": "x"}, neighbours=False)
    a11 = next(c for c in result["gate_a"] if c["id"] == "A11")
    assert a11["status"] == "pending"
    assert result["null_model"] is None
