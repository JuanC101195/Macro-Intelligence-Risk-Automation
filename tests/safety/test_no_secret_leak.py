"""Secrets must never reach logs, CLI output or error messages."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
import structlog
from typer.testing import CliRunner

from trading_system.cli import app
from trading_system.config import ConfigurationError, Settings
from trading_system.monitoring.logging import REDACTED, SecretScrubber, configure_logging

# Generated at runtime so no secret-looking literal lives in the repo (keeps gitleaks quiet).
PASSWORD = f"pw-{uuid4().hex}"
TOKEN = f"tk-{uuid4().hex}"


def test_sensitive_keys_are_redacted() -> None:
    scrub = SecretScrubber()
    event = scrub(None, "info", {"event": "x", "mt5_password": "abc", "API_KEY": "k", "n": 1})
    assert event["mt5_password"] == REDACTED
    assert event["API_KEY"] == REDACTED
    assert event["n"] == 1


def test_known_secret_values_are_scrubbed_anywhere() -> None:
    scrub = SecretScrubber([PASSWORD, TOKEN])
    event = scrub(
        None,
        "info",
        {
            "event": f"connect failed with {PASSWORD}",
            "nested": {"detail": [f"token={TOKEN}"]},
        },
    )
    assert PASSWORD not in str(event)
    assert TOKEN not in str(event)


def test_end_to_end_log_output_has_no_secrets(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    s = make_settings(mt5_password=PASSWORD, telegram_bot_token=TOKEN)
    configure_logging(secrets=s.secret_values())
    try:
        log = structlog.get_logger()
        log.info("login attempt", detail=f"password is {PASSWORD}", mt5_password=PASSWORD)
        try:
            raise RuntimeError(f"auth error {TOKEN}")
        except RuntimeError:
            log.exception("failed")
    finally:
        structlog.reset_defaults()
    out = capsys.readouterr()
    assert PASSWORD not in out.out + out.err
    assert TOKEN not in out.out + out.err


def test_settings_repr_hides_secrets(make_settings: Callable[..., Settings]) -> None:
    s = make_settings(mt5_password=PASSWORD, api_key=TOKEN)
    assert PASSWORD not in repr(s)
    assert TOKEN not in repr(s)
    assert PASSWORD not in str(s.public_summary())


def test_invalid_config_error_does_not_echo_values(
    make_settings: Callable[..., Settings],
) -> None:
    with pytest.raises(ConfigurationError) as exc:
        make_settings(trading_mode=PASSWORD)
    assert PASSWORD not in str(exc.value)


def test_cli_config_check_hides_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MT5_PASSWORD", PASSWORD)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    result = CliRunner().invoke(app, ["config", "check"])
    assert result.exit_code == 0
    assert PASSWORD not in result.output
    assert TOKEN not in result.output
