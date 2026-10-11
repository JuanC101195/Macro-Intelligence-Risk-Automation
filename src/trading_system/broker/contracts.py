"""Broker-facing data types and the read-only market data port.

See docs/architecture.md §5.2. `MetaTrader5` is imported only by
`broker/mt5_client.py` (Phase 2); everything else depends on these types.
The order-sending port (`OrderGateway`) is added in Phase 11 together with
the demo executor, so no code path can send orders before then.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from trading_system.domain import Timeframe


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Bar(_Frozen):
    """One closed candle. Prices are BID (MT5 convention). `time` is the bar open, UTC."""

    time: AwareDatetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    tick_volume: int = Field(ge=0)
    spread_points: int = Field(ge=0)
    real_volume: int | None = None

    @model_validator(mode="after")
    def _ohlc_consistent(self) -> Bar:
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("inconsistent OHLC: high/low do not contain open/close")
        return self


class Tick(_Frozen):
    time: AwareDatetime
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    spread_points: int = Field(ge=0)

    @model_validator(mode="after")
    def _ask_not_below_bid(self) -> Tick:
        if self.ask < self.bid:
            raise ValueError("ask cannot be below bid")
        return self


class SymbolSpec(_Frozen):
    symbol: str
    digits: int = Field(ge=0)
    point: float = Field(gt=0)
    tick_size: float = Field(gt=0)
    tick_value: float = Field(gt=0)  # in account currency, per 1 lot
    contract_size: float = Field(gt=0)
    volume_min: float = Field(gt=0)
    volume_max: float = Field(gt=0)
    volume_step: float = Field(gt=0)
    stops_level_points: int = Field(ge=0)
    freeze_level_points: int = Field(ge=0)
    currency_base: str
    currency_profit: str
    currency_margin: str
    trade_allowed: bool
    short_allowed: bool

    @model_validator(mode="after")
    def _volume_range(self) -> SymbolSpec:
        if self.volume_min > self.volume_max:
            raise ValueError("volume_min cannot exceed volume_max")
        return self


class AccountInfo(_Frozen):
    login_masked: str  # e.g. "****1234"; the full login never leaves broker/
    server: str
    trade_mode: Literal["demo", "contest", "real"]
    currency: str
    balance: float
    equity: float
    margin: float
    margin_free: float
    leverage: int = Field(ge=1)


class Position(_Frozen):
    ticket: int
    symbol: str
    side: Literal["buy", "sell"]
    volume: float = Field(gt=0)
    open_price: float = Field(gt=0)
    stop_loss: float | None
    take_profit: float | None
    open_time: AwareDatetime
    profit: float
    magic: int
    comment: str  # carries the intent_id when the broker keeps it


class MarketDataSource(Protocol):
    """Read-only access to the broker. Implemented by Mt5Client, FakeMt5, HistoricalDataSource."""

    def is_connected(self) -> bool: ...
    def account_info(self) -> AccountInfo: ...
    def symbol_spec(self, symbol: str) -> SymbolSpec: ...
    def closed_bars(self, symbol: str, tf: Timeframe, count: int) -> list[Bar]: ...
    def last_tick(self, symbol: str) -> Tick: ...
    def positions(self, symbol: str | None = None) -> list[Position]: ...
    def calc_margin(
        self, symbol: str, side: Literal["buy", "sell"], volume: float, price: float
    ) -> float: ...
    def calc_profit(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        volume: float,
        price_open: float,
        price_close: float,
    ) -> float: ...
