from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from trading_system import __version__
from trading_system.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_config_check_ok() -> None:
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == 0
    summary = json.loads(result.output.split("OK", 1)[1])
    assert summary["trading_mode"] == "paper"
    assert summary["live_trading_enabled"] is False


def test_config_check_fails_on_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "live")
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == 1
    assert "INVALID" in result.output
