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


def classify(x: MacroInputs) -> tuple[RiskRegime, float, list[str]]:
    """Return (regime, confidence 0..1, reasons)."""
    if x.data_stale:
        return "unknown", 0.0, ["data_stale"]
    if x.source_health < MIN_SOURCE_HEALTH:
        return "unknown", 0.0, [f"source_health<{MIN_SOURCE_HEALTH}"]
    if x.vix is None:
        return "unknown", 0.0, ["vix_missing"]

    off: list[str] = []
    on: list[str] = []

    if x.vix >= 25:
        off.append("vix>=25")
    elif x.vix <= 16:
        on.append("vix<=16")

    if x.vix_change_pct is not None:
        if x.vix_change_pct >= 10:
            off.append("vix_change>=+10%")
        elif x.vix_change_pct <= -5:
            on.append("vix_change<=-5%")

    if x.credit_spread is not None:
        if x.credit_spread >= 5.0:
            off.append("hy_spread>=5.0")
        elif x.credit_spread <= 3.5:
            on.append("hy_spread<=3.5")

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
