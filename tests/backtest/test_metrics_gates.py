from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trading_system.backtest import gates
from trading_system.backtest.metrics import (
    max_consecutive_losses,
    max_drawdown,
    profit_factor,
    session,
)
from trading_system.backtest.walk_forward import add_months, rolling_windows


def test_profit_factor() -> None:
    assert profit_factor([30, -10, 20, -10]) == pytest.approx(2.5)
    assert profit_factor([10]) == math.inf
    assert profit_factor([]) is None


def test_max_drawdown_by_hand() -> None:
    dd_abs, dd_pct = max_drawdown([100, 120, 90, 130, 104])
    assert dd_abs == 30
    assert dd_pct == pytest.approx(0.25)


def test_max_consecutive_losses() -> None:
    assert max_consecutive_losses([1, -1, -2, 3, -1, -1, -1, 2]) == 3


@pytest.mark.parametrize(("hour", "name"), [(23, "asia"), (3, "asia"), (8, "london"),
                                            (13, "london_ny_overlap"), (18, "new_york")])
def test_sessions(hour: int, name: str) -> None:
    assert session(hour) == name


def test_rolling_windows() -> None:
    start = datetime(2022, 9, 20, tzinfo=UTC)
    end = datetime(2023, 10, 1, tzinfo=UTC)
    w = rolling_windows(start, end, 6)
    assert w[0] == (start, datetime(2023, 3, 1, tzinfo=UTC))
    assert w[-1] == (datetime(2023, 9, 1, tzinfo=UTC), end)
    assert add_months(datetime(2025, 11, 15, tzinfo=UTC), 3) == datetime(2026, 2, 1, tzinfo=UTC)
    assert add_months(datetime(2026, 2, 1, tzinfo=UTC), -12) == datetime(2025, 2, 1, tzinfo=UTC)


def _metrics(**overrides: Any) -> dict[str, Any]:
    m: dict[str, Any] = {"trades": 400, "expectancy": 3.0, "profit_factor": 1.4,
                         "max_drawdown_pct": 0.06, "net_profit": 1200.0,
                         "by_year": {"2023": {"net": 500.0}, "2024": {"net": 700.0}}}
    m.update(overrides)
    return m


WINDOWS = [{"trades": 50, "net_profit": 10.0}] * 4 + [{"trades": 50, "net_profit": -5.0}]


def test_gate_a_all_pass_except_pending() -> None:
    checks = gates.gate_a(3.1, _metrics(), _metrics(profit_factor=1.1), WINDOWS,
                          neighbors={"a": 1.0, "b": 0.5})
    status = {c.id: c.status for c in checks}
    assert status["A10"] == "pending"
    assert all(s == "pass" for k, s in status.items() if k != "A10")
    assert not gates.gate_passed(checks)  # pending is not a pass


@pytest.mark.parametrize(
    ("kwargs", "failing"),
    [
        ({"history_years": 2.5}, "A1"),
        ({"base": _metrics(trades=299)}, "A2"),
        ({"base": _metrics(expectancy=-0.1)}, "A3"),
        ({"base": _metrics(profit_factor=1.19)}, "A4"),
        ({"costs_15": _metrics(profit_factor=1.0)}, "A5"),
        ({"windows": WINDOWS[:2] + [{"trades": 50, "net_profit": -1.0}] * 3}, "A6"),
        ({"base": _metrics(max_drawdown_pct=0.11)}, "A7"),
        ({"base": _metrics(net_profit=600.0)}, "A8"),  # 600 - best year 700 < 0
        ({"neighbors": {"a": 1.0, "b": -0.2}}, "A9"),
    ],
)
def test_gate_a_failures(kwargs: dict[str, Any], failing: str) -> None:
    args: dict[str, Any] = {"history_years": 3.1, "base": _metrics(),
                            "costs_15": _metrics(profit_factor=1.1), "windows": WINDOWS,
                            "neighbors": {"a": 1.0}}
    args.update(kwargs)
    checks = {c.id: c.status for c in gates.gate_a(**args)}
    assert checks[failing] == "fail"


def test_holdout_can_be_claimed_once(tmp_path: Path) -> None:
    marker = tmp_path / "holdout_used.json"
    gates.claim_holdout(marker, "cfg1")
    with pytest.raises(gates.HoldoutAlreadyUsedError, match="already evaluated"):
        gates.claim_holdout(marker, "cfg2")
