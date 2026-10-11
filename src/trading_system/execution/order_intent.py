"""OrderIntent, ExecutionResult and the Executor port (docs/architecture.md §5.6-5.7).

This module holds only types, so risk/ can build intents without importing
any executor. Executors (paper, demo) arrive in Phases 7 and 11.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_system.broker.contracts import Position
from trading_system.domain import Side, Timeframe, bracket_error

# "live" is deliberately absent: an intent for live trading cannot even be constructed.
IntentMode = Literal["backtest", "paper", "demo"]

_INTENT_ID = re.compile(r"^[0-9a-f]{16}$")


def make_intent_id(
    strategy_version: str, symbol: str, timeframe: Timeframe, bar_time: datetime, side: Side
) -> str:
    """Deterministic idempotency key: the same signal always maps to the same id.

    16 hex chars fit in the MT5 order comment (max 31 chars).
    """
    raw = f"{strategy_version}|{symbol}|{timeframe.value}|{bar_time.isoformat()}|{side.value}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class OrderIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_id: str
    signal_id: str
    signal_bar_time: AwareDatetime
    symbol: str
    side: Literal["buy", "sell"]
    entry_price: float
    stop_loss: float  # mandatory: there are no orders without a stop
    take_profit: float
    volume: float = Field(gt=0)
    risk_amount: float = Field(gt=0)
    strategy_version: str
    model_version: str | None = None
    mode: IntentMode
    reason: str = Field(min_length=1)

    @field_validator("intent_id")
    @classmethod
    def _intent_id_format(cls, value: str) -> str:
        if not _INTENT_ID.match(value):
            raise ValueError("intent_id must be 16 lowercase hex chars (see make_intent_id)")
        return value

    @model_validator(mode="after")
    def _valid_bracket(self) -> OrderIntent:
        error = bracket_error(
            self.side == "buy", self.entry_price, self.stop_loss, self.take_profit
        )
        if error:
            raise ValueError(error)
        return self


class ExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_id: str
    status: Literal["filled", "rejected", "duplicate", "error", "unknown"]
    broker_ticket: int | None = None
    fill_price: float | None = None
    fill_time: AwareDatetime | None = None
    slippage_points: float | None = None
    commission: float = 0.0
    swap: float = 0.0
    message: str = ""  # sanitized broker response


class Executor(Protocol):
    mode: IntentMode

    def submit(self, intent: OrderIntent) -> ExecutionResult: ...
    def close(self, ticket: int, reason: str) -> ExecutionResult: ...
    def sync(self) -> list[Position]: ...
