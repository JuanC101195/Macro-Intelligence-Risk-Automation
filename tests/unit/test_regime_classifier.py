from __future__ import annotations

from dataclasses import replace

import pytest

from trading_system.macro.regime_classifier import MacroInputs, classify

CALM = MacroInputs(vix=14.0, vix_change_pct=-6.0, yield_curve=0.4, credit_spread=3.0,
                   gold_change_pct=0.1, source_health=1.0, data_stale=False)
STRESS = MacroInputs(vix=32.0, vix_change_pct=18.0, yield_curve=-0.2, credit_spread=5.5,
                     gold_change_pct=2.0, source_health=1.0, data_stale=False)


def test_calm_market_is_risk_on() -> None:
    regime, confidence, reasons = classify(CALM)
    assert regime == "risk_on"
    assert confidence == 1.0
    assert "vix<=16" in reasons


def test_stress_is_risk_off_and_inversion_reinforces() -> None:
    regime, confidence, reasons = classify(STRESS)
    assert regime == "risk_off"
    assert "yield_curve_inverted" in reasons
    assert confidence == 1.0


def test_inverted_curve_alone_is_not_risk_off() -> None:
    regime, _, reasons = classify(replace(CALM, yield_curve=-0.5))
    assert regime == "risk_on"
    assert "yield_curve_inverted" not in reasons


def test_conflicting_signals_are_mixed() -> None:
    regime, confidence, _ = classify(replace(CALM, vix=27.0, vix_change_pct=None))
    assert regime == "mixed"
    assert confidence < 1.0


@pytest.mark.parametrize(
    ("change", "reason"),
    [({"data_stale": True}, "data_stale"),
     ({"source_health": 0.3}, "source_health<0.5"),
     ({"vix": None}, "vix_missing")],
)
def test_unknown_when_inputs_untrustworthy(change: dict[str, object], reason: str) -> None:
    regime, confidence, reasons = classify(replace(CALM, **change))  # type: ignore[arg-type]
    assert regime == "unknown"
    assert confidence == 0.0
    assert reasons == [reason]


def test_confidence_scaled_by_source_health() -> None:
    _, confidence, _ = classify(replace(CALM, source_health=0.6))
    assert confidence == pytest.approx(0.6)
