"""Shared fixtures for risk tests: symbol specs, accounts and a fake MT5 calculator."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from trading_system.broker.contracts import AccountInfo, Position, SymbolSpec

NOW = datetime(2026, 10, 14, 13, 45, 3, tzinfo=UTC)


def spec(symbol: str = "EURUSD", **overrides: Any) -> SymbolSpec:
    jpy = symbol.endswith("JPY")
    data: dict[str, Any] = {
        "symbol": symbol, "digits": 3 if jpy else 5, "point": 1e-3 if jpy else 1e-5,
        "tick_size": 1e-3 if jpy else 1e-5,
        "tick_value": 100 / 150.0 if jpy else 1.0,  # USD account
        "contract_size": 100_000, "volume_min": 0.01, "volume_max": 100.0,
        "volume_step": 0.01, "stops_level_points": 0, "freeze_level_points": 0,
        "currency_base": symbol[:3], "currency_profit": symbol[3:],
        "currency_margin": symbol[:3], "trade_allowed": True, "short_allowed": True,
    }
    data.update(overrides)
    return SymbolSpec(**data)


def account(**overrides: Any) -> AccountInfo:
    data: dict[str, Any] = {
        "login_masked": "****9960", "server": "MetaQuotes-Demo", "trade_mode": "demo",
        "currency": "USD", "balance": 10_000.0, "equity": 10_000.0, "margin": 0.0,
        "margin_free": 10_000.0, "leverage": 100,
    }
    data.update(overrides)
    return AccountInfo(**data)


def position(symbol: str = "EURUSD", side: Literal["buy", "sell"] = "buy",
             volume: float = 0.12, open_price: float = 1.0800,
             stop_loss: float | None = 1.0780, **overrides: Any) -> Position:
    data: dict[str, Any] = {
        "ticket": 1, "symbol": symbol, "side": side, "volume": volume,
        "open_price": open_price, "stop_loss": stop_loss, "take_profit": None,
        "open_time": NOW, "profit": 0.0, "magic": 777, "comment": "",
    }
    data.update(overrides)
    return Position(**data)


class FakeQuotes:
    """Same arithmetic as MT5 order_calc_* for a USD account at 1:100."""

    def __init__(self, margin_per_lot: float = 1_082.5) -> None:
        self.margin_per_lot = margin_per_lot

    def calc_margin(self, symbol: str, side: str, volume: float, price: float) -> float:
        return volume * self.margin_per_lot

    def calc_profit(self, symbol: str, side: str, volume: float,
                    price_open: float, price_close: float) -> float:
        sign = 1 if side == "buy" else -1
        raw = sign * (price_close - price_open) * volume * 100_000
        return raw / price_close if symbol.endswith("JPY") else raw
