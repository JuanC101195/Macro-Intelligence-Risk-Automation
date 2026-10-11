from __future__ import annotations

from collections.abc import Callable

import pytest

from trading_system.config import ConfigurationError, Settings


def test_defaults_match_risk_policy(make_settings: Callable[..., Settings]) -> None:
    s = make_settings()
    assert s.max_risk_per_trade == 0.0025
    assert s.max_daily_loss == 0.02
    assert s.max_open_positions == 1
    assert s.symbols == ("EURUSD", "GBPUSD", "USDJPY")
    assert s.macro_required is False


def test_symbols_parsed_from_env(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    monkeypatch.setenv("SYMBOLS", " eurusd , usdjpy ")
    monkeypatch.setenv("DEFAULT_SYMBOL", "usdjpy")
    s = make_settings()
    assert s.symbols == ("EURUSD", "USDJPY")
    assert s.default_symbol == "USDJPY"


def test_default_symbol_must_be_listed(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ConfigurationError, match="DEFAULT_SYMBOL"):
        make_settings(symbols="EURUSD", default_symbol="GBPUSD")


def test_empty_symbols_rejected(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ConfigurationError, match="SYMBOLS"):
        make_settings(symbols="")


def test_macro_required_needs_crucix(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ConfigurationError, match="CRUCIX_ENABLED"):
        make_settings(macro_required=True, crucix_enabled=False)


def test_production_requires_api_key(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ConfigurationError, match="API_KEY"):
        make_settings(app_env="production")
    assert make_settings(app_env="production", api_key="k" * 32).api_key is not None


def test_empty_secret_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    monkeypatch.setenv("MT5_PASSWORD", "")
    assert make_settings().mt5_password is None


def test_all_errors_reported_together(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ConfigurationError) as exc:
        make_settings(live_trading_enabled=True, allow_demo_orders=True)
    assert "LIVE_TRADING_ENABLED" in str(exc.value)
    assert "ALLOW_DEMO_ORDERS" in str(exc.value)
