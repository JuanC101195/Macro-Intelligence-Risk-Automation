from __future__ import annotations

import random

import pytest

from tests.fixtures.risk_fixtures import spec
from trading_system.risk.position_sizing import size_position


def test_eurusd_example_from_risk_policy() -> None:
    # docs/risk-policy.md: 10 000 USD, 0.25 %, 1.08250 -> 1.08050 => 0.12 lots, 24 USD
    r = size_position(10_000, 0.0025, 1.08250, 1.08050, spec("EURUSD"))
    assert r.volume == 0.12
    assert r.risk_money_allowed == pytest.approx(25.0)
    assert r.risk_money_real == pytest.approx(24.0)
    assert r.loss_per_lot == pytest.approx(200.0)


def test_usdjpy_example_from_risk_policy() -> None:
    # 150.000 -> 149.700, tick_value 100/150 USD => 200 USD per lot => 0.12 lots
    r = size_position(10_000, 0.0025, 150.000, 149.700, spec("USDJPY"))
    assert r.volume == 0.12
    assert r.risk_money_real == pytest.approx(24.0)


def test_always_rounds_down() -> None:
    # raw volume 0.1299 -> 0.12, never 0.13
    r = size_position(10_000, 0.0025, 1.08250, 1.08250 - 0.0019246, spec())
    assert r.volume == 0.12


def test_exact_step_is_not_lost_to_float_noise() -> None:
    # 24 USD / 200 USD per lot = exactly 0.12
    r = size_position(9_600, 0.0025, 1.08250, 1.08050, spec())
    assert r.volume == 0.12


def test_below_minimum_is_rejected_not_rounded_up() -> None:
    r = size_position(100, 0.0025, 1.08250, 1.08050, spec())  # 0.25 USD of risk
    assert r.volume is None
    assert r.rejection == "volume_below_min"


def test_capped_at_maximum_volume() -> None:
    r = size_position(1e9, 0.005, 1.08250, 1.08050, spec(volume_max=50.0))
    assert r.volume == 50.0


@pytest.mark.parametrize(("equity", "risk", "stop"), [(0, 0.0025, 1.08), (10_000, 0, 1.08),
                                                      (10_000, 0.0025, 1.0825)])
def test_degenerate_inputs_rejected(equity: float, risk: float, stop: float) -> None:
    assert size_position(equity, risk, 1.0825, stop, spec()).volume is None


def test_real_risk_never_exceeds_allowed() -> None:
    rng = random.Random(1)  # noqa: S311 - reproducible test data
    for _ in range(2_000):
        equity = rng.uniform(500, 200_000)
        risk = rng.uniform(0.001, 0.005)
        entry = rng.uniform(0.9, 1.5)
        stop = entry - rng.uniform(0.0003, 0.01)
        s = spec(volume_step=rng.choice([0.01, 0.1]))
        r = size_position(equity, risk, entry, stop, s)
        if r.volume is not None:
            assert r.risk_money_real <= r.risk_money_allowed * (1 + 1e-9)
            assert r.volume >= s.volume_min
