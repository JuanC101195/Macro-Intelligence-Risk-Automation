"""The circuit breaker must survive restarts, fail closed and only reset by hand."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.risk_fixtures import NOW
from trading_system.risk.circuit_breaker import FileCircuitBreaker


def _breaker(path: Path) -> FileCircuitBreaker:
    return FileCircuitBreaker(path, clock=lambda: NOW)


def test_fresh_install_is_closed(tmp_path: Path) -> None:
    assert not _breaker(tmp_path / "b.json").is_open()


def test_trip_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    _breaker(path).trip("daily_loss_limit", source="risk")
    restarted = _breaker(path)
    assert restarted.is_open()
    assert restarted.state().reason == "daily_loss_limit"
    assert not path.with_suffix(".json.tmp").exists()  # atomic write leaves no temp file


def test_first_reason_is_kept(tmp_path: Path) -> None:
    b = _breaker(tmp_path / "b.json")
    b.trip("mt5_disconnected", source="broker")
    b.trip("stale_data", source="loop")
    assert b.state().reason == "mt5_disconnected"
    assert b.history[-1]["event"] == "trip_ignored_already_open"


def test_reset_is_manual_and_audited(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    b = _breaker(path)
    b.trip("daily_loss_limit", source="risk")
    with pytest.raises(ValueError, match="operator"):
        b.reset("", "checked")
    with pytest.raises(ValueError, match="reason"):
        b.reset("juan", " ")
    b.reset("juan", "new trading day, positions reviewed")
    restarted = _breaker(path)
    assert not restarted.is_open()
    last = restarted.history[-1]
    assert last["event"] == "reset"
    assert last["operator"] == "juan"
    assert last["previous_reason"] == "daily_loss_limit"


@pytest.mark.parametrize("content", ["{not json", '{"history": []}', '{"state": {"x": 1}}', ""])
def test_corrupt_state_starts_open(tmp_path: Path, content: str) -> None:
    path = tmp_path / "b.json"
    path.write_text(content, encoding="utf-8")
    b = _breaker(path)
    assert b.is_open()
    assert b.state().reason == "inconsistent_state_on_startup"


def test_kill_switch(tmp_path: Path) -> None:
    b = _breaker(tmp_path / "b.json")
    b.kill("juan", "news event")
    assert b.is_open()
    assert b.state().reason == "manual_kill: news event"
    assert b.state().source == "operator:juan"
