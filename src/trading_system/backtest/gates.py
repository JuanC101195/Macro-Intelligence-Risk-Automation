"""ADR 0002 Gate A (research -> paper) evaluated automatically, plus the hold-out lock.

Thresholds are copied from docs/decisions/0002-criterios-de-exito-y-parada.md and
must not be changed without a new ADR written BEFORE re-evaluating.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Status = Literal["pass", "fail", "pending"]

MIN_HISTORY_YEARS = 3.0
MIN_OOS_TRADES = 300
MIN_PROFIT_FACTOR = 1.20
MIN_PROFIT_FACTOR_COSTS_15 = 1.00
MIN_POSITIVE_WINDOWS = 0.60
MAX_DRAWDOWN_PCT = 0.10
HOLDOUT_MIN_PROFIT_FACTOR = 1.10
HOLDOUT_MONTHS = 12


@dataclass(frozen=True)
class GateCheck:
    id: str
    criterion: str
    threshold: str
    value: str
    status: Status


def _pf(value: float | None) -> float:
    return 0.0 if value is None else value


def _status(ok: bool | None) -> Status:
    if ok is None:
        return "pending"
    return "pass" if ok else "fail"


def _show(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _check(cid: str, criterion: str, threshold: str, value: Any, ok: bool | None) -> GateCheck:
    return GateCheck(cid, criterion, threshold, _show(value), _status(ok))


def _positive_share(windows: Sequence[Mapping[str, Any]]) -> float:
    traded = [w for w in windows if w["trades"] > 0]
    if not traded:
        return 0.0
    return sum(1 for w in traded if w["net_profit"] > 0) / len(traded)


def _net_without_best_year(base: Mapping[str, Any]) -> float | None:
    years = base.get("by_year", {})
    if not years:
        return None
    return float(base["net_profit"] - max(y["net"] for y in years.values()))


def _all_positive(values: Mapping[str, float | None] | None) -> bool | None:
    if not values:
        return None
    return all(v is not None and v > 0 for v in values.values())


def _holdout_ok(holdout: Mapping[str, Any] | None) -> bool | None:
    if holdout is None:
        return None
    return ((holdout["expectancy"] or 0) > 0
            and _pf(holdout["profit_factor"]) >= HOLDOUT_MIN_PROFIT_FACTOR)


def gate_a(
    history_years: float,
    base: Mapping[str, Any],
    costs_15: Mapping[str, Any],
    windows: Sequence[Mapping[str, Any]],
    neighbors: Mapping[str, float | None] | None = None,
    holdout: Mapping[str, Any] | None = None,
) -> list[GateCheck]:
    """A1-A10. `neighbors` maps variant name -> expectancy; `holdout` is its metrics."""
    trades = base["trades"]
    expectancy = base["expectancy"]
    positive_share = _positive_share(windows)
    without_best = _net_without_best_year(base)
    neighbor_ok = _all_positive(neighbors)
    hold_ok = _holdout_ok(holdout)

    return [
        _check("A1", "History (excluding hold-out)", f">= {MIN_HISTORY_YEARS} years",
               history_years, history_years >= MIN_HISTORY_YEARS),
        _check("A2", "Out-of-sample trades", f">= {MIN_OOS_TRADES}", trades,
               trades >= MIN_OOS_TRADES),
        _check("A3", "Net expectancy per trade (costs x1)", "> 0", expectancy,
               expectancy is not None and expectancy > 0),
        _check("A4", "Profit factor (costs x1)", f">= {MIN_PROFIT_FACTOR}",
               base["profit_factor"], _pf(base["profit_factor"]) >= MIN_PROFIT_FACTOR),
        _check("A5", "Profit factor (costs x1.5)", f"> {MIN_PROFIT_FACTOR_COSTS_15}",
               costs_15["profit_factor"],
               _pf(costs_15["profit_factor"]) > MIN_PROFIT_FACTOR_COSTS_15),
        _check("A6", "Positive walk-forward windows", f">= {MIN_POSITIVE_WINDOWS:.0%}",
               positive_share, positive_share >= MIN_POSITIVE_WINDOWS),
        _check("A7", "Max drawdown at 0.25% risk", f"<= {MAX_DRAWDOWN_PCT:.0%}",
               base["max_drawdown_pct"], base["max_drawdown_pct"] <= MAX_DRAWDOWN_PCT),
        _check("A8", "Net profit without the best year", "> 0", without_best,
               None if without_best is None else without_best > 0),
        _check("A9", "Neighbouring parameters keep expectancy > 0", "all > 0",
               None if not neighbors else ", ".join(
                   f"{k}={v:.2f}" if v is not None else f"{k}=-" for k, v in neighbors.items()),
               neighbor_ok),
        _check("A10", "Hold-out (evaluated once)",
               f"expectancy > 0 and PF >= {HOLDOUT_MIN_PROFIT_FACTOR}",
               None if holdout is None else holdout["profit_factor"], hold_ok),
    ]


def gate_passed(checks: Sequence[GateCheck]) -> bool:
    return all(c.status == "pass" for c in checks)


class HoldoutAlreadyUsedError(RuntimeError):
    pass


def claim_holdout(marker: Path, config_fingerprint: str) -> None:
    """Record the single permitted hold-out evaluation (ADR 0002 rule 2)."""
    if marker.exists():
        used = json.loads(marker.read_text(encoding="utf-8"))
        raise HoldoutAlreadyUsedError(
            f"hold-out already evaluated at {used.get('at')} (config {used.get('config')}); "
            "it no longer counts as out-of-sample"
        )
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"at": datetime.now(UTC).isoformat(),
                                  "config": config_fingerprint}), encoding="utf-8")
