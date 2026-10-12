"""Rule-based risk-on / risk-off classifier (baseline, not tuned).

Thresholds are round, widely used reference levels, chosen BEFORE looking at any
backtest so they cannot be overfitted (ADR 0002). Changing them is a new version.
"""

from __future__ import annotations

from dataclasses import dataclass

from trading_system.macro.macro_context import RiskRegime

VERSION = "regime-rules-v001"

MIN_SOURCE_HEALTH = 0.5


@dataclass(frozen=True)
class MacroInputs:
    vix: float | None
    vix_change_pct: float | None
    yield_curve: float | None
    credit_spread: float | None
    gold_change_pct: float | None
    source_health: float
    data_stale: bool


def _band(
    value: float | None, off_at: float, on_at: float, off_name: str, on_name: str
) -> tuple[list[str], list[str]]:
    """value >= off_at -> risk-off reason; value <= on_at -> risk-on reason."""
    if value is None:
        return [], []
    if value >= off_at:
        return [off_name], []
    if value <= on_at:
        return [], [on_name]
    return [], []


def _untrustworthy(x: MacroInputs) -> str | None:
    if x.data_stale:
        return "data_stale"
    if x.source_health < MIN_SOURCE_HEALTH:
        return f"source_health<{MIN_SOURCE_HEALTH}"
    if x.vix is None:
        return "vix_missing"
    return None


def classify(x: MacroInputs) -> tuple[RiskRegime, float, list[str]]:
    """Return (regime, confidence 0..1, reasons)."""
    problem = _untrustworthy(x)
    if problem:
        return "unknown", 0.0, [problem]

    off: list[str] = []
    on: list[str] = []
    for value, off_at, on_at, off_name, on_name in (
        (x.vix, 25.0, 16.0, "vix>=25", "vix<=16"),
        (x.vix_change_pct, 10.0, -5.0, "vix_change>=+10%", "vix_change<=-5%"),
        (x.credit_spread, 5.0, 3.5, "hy_spread>=5.0", "hy_spread<=3.5"),
    ):
        o, n = _band(value, off_at, on_at, off_name, on_name)
        off += o
        on += n

    if x.gold_change_pct is not None and x.gold_change_pct >= 1.5:
        off.append("gold_change>=+1.5%")

    # Inverted curve is slow-moving: it only reinforces an existing risk-off reading.
    if x.yield_curve is not None and x.yield_curve < 0 and off:
        off.append("yield_curve_inverted")

    reasons = off + on
    if len(off) >= 2 and len(off) > len(on):
        regime: RiskRegime = "risk_off"
    elif len(on) >= 2 and not off:
        regime = "risk_on"
    else:
        regime = "mixed"

    margin = abs(len(off) - len(on))
    confidence = min(1.0, margin / 3) * x.source_health
    return regime, round(confidence, 4), reasons
