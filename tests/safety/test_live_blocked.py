"""Live trading must be impossible to configure during the MVP."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from trading_system.config import ConfigurationError, Settings
from trading_system.domain import TradingMode


def test_default_mode_is_paper(make_settings: Callable[..., Settings]) -> None:
    s = make_settings()
    assert s.trading_mode is TradingMode.PAPER
    assert s.live_trading_enabled is False
    assert s.allow_demo_orders is False


def test_live_mode_is_rejected(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ConfigurationError, match="live is blocked"):
        make_settings(trading_mode="live")


def test_live_flag_is_rejected_even_in_paper(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ConfigurationError, match="LIVE_TRADING_ENABLED"):
        make_settings(live_trading_enabled=True)


def test_live_cannot_be_unlocked_by_combining_flags(
    make_settings: Callable[..., Settings],
) -> None:
    with pytest.raises(ConfigurationError, match="live is blocked"):
        make_settings(trading_mode="live", live_trading_enabled=True, allow_demo_orders=True)


def test_live_rejected_from_environment(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    monkeypatch.setenv("TRADING_MODE", "live")
    with pytest.raises(ConfigurationError):
        make_settings()


def test_live_rejected_from_env_file(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    from trading_system.config import load_settings

    monkeypatch.chdir(str(tmp_path))
    with open(".env", "w", encoding="utf-8") as fh:
        fh.write("TRADING_MODE=live\n")
    with pytest.raises(ConfigurationError):
        load_settings()


def test_demo_requires_explicit_opt_in(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ConfigurationError, match="ALLOW_DEMO_ORDERS=true"):
        make_settings(trading_mode="demo")


def test_demo_opt_in_outside_demo_is_ambiguous(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ConfigurationError, match="only valid with TRADING_MODE=demo"):
        make_settings(allow_demo_orders=True)


def test_demo_with_opt_in_is_accepted(make_settings: Callable[..., Settings]) -> None:
    s = make_settings(trading_mode="demo", allow_demo_orders=True)
    assert s.trading_mode is TradingMode.DEMO


def test_unknown_mode_is_rejected(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ConfigurationError, match="trading_mode"):
        make_settings(trading_mode="real")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_risk_per_trade", 0.0051),
        ("max_risk_per_trade", 0.05),
        ("max_daily_loss", 0.021),
        ("max_open_positions", 4),
        ("max_consecutive_losses", 6),
        ("max_trades_per_day", 11),
    ],
)
def test_risk_ceilings(make_settings: Callable[..., Settings], field: str, value: float) -> None:
    with pytest.raises(ConfigurationError):
        make_settings(**{field: value})


@pytest.mark.parametrize("value", [0, -0.01])
def test_risk_must_be_positive(make_settings: Callable[..., Settings], value: float) -> None:
    with pytest.raises(ConfigurationError):
        make_settings(max_risk_per_trade=value)


def test_settings_are_immutable(make_settings: Callable[..., Settings]) -> None:
    s = make_settings()
    with pytest.raises(ValidationError, match="frozen"):
        s.trading_mode = TradingMode.LIVE  # type: ignore[misc]
