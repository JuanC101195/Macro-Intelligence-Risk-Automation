from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from trading_system.config import ConfigurationError, Settings, load_settings


def test_env_example_loads_as_is() -> None:
    """A fresh copy of .env.example must be a valid, safe configuration."""
    example = Path(__file__).resolve().parents[2] / ".env.example"
    s = load_settings(_env_file=example)
    assert s.trading_mode.value == "paper"
    assert s.n8n_base_url is None
    assert s.mt5_login is None


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


@pytest.mark.parametrize(
    "url",
    ["ftp://crucix:3117", "file:///etc/passwd", "http://user:pw@crucix:3117",
     "http://crucix:3117/?redirect=evil", "not a url"],
)
def test_crucix_url_must_be_plain_http(make_settings: Callable[..., Settings], url: str) -> None:
    with pytest.raises(ConfigurationError, match="crucix_base_url"):
        make_settings(crucix_base_url=url)


def test_crucix_url_accepts_http_and_https(make_settings: Callable[..., Settings]) -> None:
    assert make_settings(crucix_base_url="https://crucix.local:3117").crucix_base_url


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
