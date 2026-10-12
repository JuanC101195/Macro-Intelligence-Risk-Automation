"""Application settings with fail-fast validation.

Every rule here comes from docs/architecture.md §3 and docs/risk-policy.md §1.
Any dangerous or ambiguous combination raises at startup: the system never
"guesses" its way into a riskier mode.
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import urlparse

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from trading_system.domain import AppEnv, Timeframe, TradingMode

# Hard ceilings for the MVP. Configuration can go lower, never higher.
MAX_RISK_PER_TRADE_CEILING = 0.005
MAX_DAILY_LOSS_CEILING = 0.02
MAX_OPEN_POSITIONS_CEILING = 3
MAX_CONSECUTIVE_LOSSES_CEILING = 5
MAX_TRADES_PER_DAY_CEILING = 10


class ConfigurationError(Exception):
    """Raised when the configuration is unsafe, ambiguous or malformed.

    Not a ValueError on purpose: pydantic propagates it unchanged instead of
    wrapping it, so callers always get one exception type with a clear message.
    """


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_env: AppEnv = AppEnv.DEVELOPMENT
    trading_mode: TradingMode = TradingMode.PAPER
    live_trading_enabled: bool = False
    allow_demo_orders: bool = False

    mt5_login: SecretStr | None = None
    mt5_password: SecretStr | None = None
    mt5_server: str | None = None
    mt5_path: str | None = None
    mt5_timeout_ms: int = Field(default=10_000, ge=1000)
    # Server time minus UTC, in minutes (e.g. 180 for UTC+3). Required to read MT5 data;
    # `trading-system mt5 check` prints the observed value. Mismatches stop the client.
    mt5_server_utc_offset_minutes: int | None = Field(default=None, ge=-720, le=840)

    symbols: Annotated[tuple[str, ...], NoDecode] = ("EURUSD", "GBPUSD", "USDJPY")
    default_symbol: str = "EURUSD"
    default_timeframe: Timeframe = Timeframe.M15

    max_risk_per_trade: float = Field(default=0.0025, gt=0)
    max_daily_loss: float = Field(default=0.02, gt=0)
    max_open_positions: int = Field(default=1, ge=1)
    max_consecutive_losses: int = Field(default=3, ge=1)
    max_trades_per_day: int = Field(default=5, ge=1)
    max_spread_points: int = Field(default=30, ge=1)
    max_slippage_points: int = Field(default=10, ge=0)

    crucix_base_url: str = "http://127.0.0.1:3117"
    crucix_enabled: bool = True
    macro_required: bool = False
    macro_max_age_minutes: int = Field(default=30, ge=1)
    macro_unknown_penalty: float = Field(default=0.8, gt=0, le=1)

    database_url: str = "sqlite:///./trading.db"

    api_key: SecretStr | None = None
    n8n_api_key: SecretStr | None = None
    n8n_base_url: str | None = None

    llm_api_key: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    discord_bot_token: SecretStr | None = None
    discord_webhook_url: SecretStr | None = None

    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("symbols", mode="before")
    @classmethod
    def _split_symbols(cls, value: Any) -> Any:
        if isinstance(value, str):
            return tuple(s.strip().upper() for s in value.split(",") if s.strip())
        return value

    @field_validator("crucix_base_url", "n8n_base_url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        # Only plain http(s) base URLs; no credentials, query strings or other schemes.
        if value is None:
            return value
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("must be an http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("must not contain credentials, query or fragment")
        return value

    @field_validator("default_symbol", mode="before")
    @classmethod
    def _upper_symbol(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator(
        "mt5_login",
        "mt5_password",
        "api_key",
        "n8n_api_key",
        "llm_api_key",
        "telegram_bot_token",
        "discord_bot_token",
        "discord_webhook_url",
        "mt5_server",
        "mt5_path",
        "mt5_server_utc_offset_minutes",
        "n8n_base_url",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_safety(self) -> Settings:
        errors = list(_safety_errors(self))
        if errors:
            raise ConfigurationError("Unsafe configuration: " + "; ".join(errors))
        return self

    def public_summary(self) -> dict[str, Any]:
        """Non-sensitive view of the settings, safe for logs, CLI and /health."""
        return {
            "app_env": self.app_env.value,
            "trading_mode": self.trading_mode.value,
            "live_trading_enabled": self.live_trading_enabled,
            "allow_demo_orders": self.allow_demo_orders,
            "symbols": list(self.symbols),
            "default_timeframe": self.default_timeframe.value,
            "max_risk_per_trade": self.max_risk_per_trade,
            "max_daily_loss": self.max_daily_loss,
            "max_open_positions": self.max_open_positions,
            "crucix_enabled": self.crucix_enabled,
            "macro_required": self.macro_required,
            "mt5_configured": self.mt5_login is not None,
            "api_key_configured": self.api_key is not None,
        }

    def secret_values(self) -> list[str]:
        """Raw secret values, used only by the log sanitizer to scrub them."""
        fields = (
            self.mt5_login,
            self.mt5_password,
            self.api_key,
            self.n8n_api_key,
            self.llm_api_key,
            self.telegram_bot_token,
            self.discord_bot_token,
            self.discord_webhook_url,
        )
        return [f.get_secret_value() for f in fields if f is not None and f.get_secret_value()]


def _safety_errors(s: Settings) -> list[str]:
    # (violated?, message). Each rule is one line so the policy is auditable at a glance.
    rules: list[tuple[bool, str]] = [
        # Live trading is blocked for the whole MVP, whatever else is set.
        (s.trading_mode is TradingMode.LIVE, "TRADING_MODE=live is blocked during the MVP"),
        (s.live_trading_enabled, "LIVE_TRADING_ENABLED=true is blocked during the MVP"),
        # Demo needs an explicit opt-in, and the opt-in only makes sense in demo.
        (
            s.trading_mode is TradingMode.DEMO and not s.allow_demo_orders,
            "TRADING_MODE=demo requires ALLOW_DEMO_ORDERS=true",
        ),
        (
            s.allow_demo_orders and s.trading_mode is not TradingMode.DEMO,
            "ALLOW_DEMO_ORDERS=true is only valid with TRADING_MODE=demo",
        ),
        (
            s.max_risk_per_trade > MAX_RISK_PER_TRADE_CEILING,
            f"MAX_RISK_PER_TRADE must be <= {MAX_RISK_PER_TRADE_CEILING}",
        ),
        (
            s.max_daily_loss > MAX_DAILY_LOSS_CEILING,
            f"MAX_DAILY_LOSS must be <= {MAX_DAILY_LOSS_CEILING}",
        ),
        (
            s.max_risk_per_trade > s.max_daily_loss,
            "MAX_RISK_PER_TRADE cannot exceed MAX_DAILY_LOSS",
        ),
        (
            s.max_open_positions > MAX_OPEN_POSITIONS_CEILING,
            f"MAX_OPEN_POSITIONS must be <= {MAX_OPEN_POSITIONS_CEILING}",
        ),
        (
            s.max_consecutive_losses > MAX_CONSECUTIVE_LOSSES_CEILING,
            f"MAX_CONSECUTIVE_LOSSES must be <= {MAX_CONSECUTIVE_LOSSES_CEILING}",
        ),
        (
            s.max_trades_per_day > MAX_TRADES_PER_DAY_CEILING,
            f"MAX_TRADES_PER_DAY must be <= {MAX_TRADES_PER_DAY_CEILING}",
        ),
        (
            s.macro_required and not s.crucix_enabled,
            "MACRO_REQUIRED=true needs CRUCIX_ENABLED=true",
        ),
        (not s.symbols, "SYMBOLS cannot be empty"),
        (s.default_symbol not in s.symbols, "DEFAULT_SYMBOL must be one of SYMBOLS"),
        (
            s.app_env is AppEnv.PRODUCTION and s.api_key is None,
            "APP_ENV=production requires API_KEY",
        ),
    ]
    return [message for violated, message in rules if violated]


def load_settings(**overrides: Any) -> Settings:
    """Load settings from environment and .env. Raises ConfigurationError if unsafe."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        fields = ", ".join(".".join(str(p) for p in e["loc"]) or "settings" for e in exc.errors())
        # Values are left out on purpose: they could be secrets.
        raise ConfigurationError(f"Invalid configuration values for: {fields}") from None
