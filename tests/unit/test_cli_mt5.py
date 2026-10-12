from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.fixtures.fake_mt5 import FakeMt5
from trading_system import cli
from trading_system.broker.mt5_client import Mt5Client
from trading_system.config import Settings

NOW = datetime(2026, 10, 14, 13, 37, 12, tzinfo=UTC)
runner = CliRunner()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeMt5:
    fake = FakeMt5(now=NOW)

    def from_settings(settings: Settings, mt5_module: Any = None) -> Mt5Client:
        return Mt5Client(
            fake,
            login=settings.mt5_login.get_secret_value() if settings.mt5_login else None,
            password=settings.mt5_password.get_secret_value() if settings.mt5_password else None,
            utc_offset_minutes=settings.mt5_server_utc_offset_minutes,
            clock=lambda: NOW,
        )

    monkeypatch.setattr(cli.Mt5Client, "from_settings", staticmethod(from_settings))
    monkeypatch.setenv("MT5_LOGIN", str(fake.login))
    monkeypatch.setenv("MT5_PASSWORD", "very-secret-pw")
    monkeypatch.setenv("MT5_SERVER_UTC_OFFSET_MINUTES", "180")
    return fake


def test_mt5_check_suggests_offset_when_missing(
    fake: FakeMt5, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MT5_SERVER_UTC_OFFSET_MINUTES")
    result = runner.invoke(cli.app, ["mt5", "check"])
    assert result.exit_code == 1
    assert "MT5_SERVER_UTC_OFFSET_MINUTES=180" in result.output


def test_mt5_check_demo(fake: FakeMt5) -> None:
    result = runner.invoke(cli.app, ["mt5", "check"])
    assert result.exit_code == 0, result.output
    assert '"trade_mode": "demo"' in result.output
    assert "USDJPY" in result.output
    assert "very-secret-pw" not in result.output
    assert str(fake.login) not in result.output


def test_mt5_check_real_account_exits_2(fake: FakeMt5) -> None:
    fake.trade_mode = 2
    result = runner.invoke(cli.app, ["mt5", "check"])
    assert result.exit_code == 2
    assert "not demo" in result.output


def test_mt5_check_connection_error(fake: FakeMt5) -> None:
    fake.fail.add("initialize")
    result = runner.invoke(cli.app, ["mt5", "check"])
    assert result.exit_code == 1
    assert "very-secret-pw" not in result.output
