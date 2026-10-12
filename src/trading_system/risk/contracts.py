"""Risk limits, decisions and ports (docs/risk-policy.md, docs/architecture.md §5.6).

The RiskEngine (Phase 5) is the only component allowed to build an OrderIntent.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from trading_system.broker.contracts import AccountInfo, Position, SymbolSpec, Tick
from trading_system.config import Settings
from trading_system.execution.order_intent import OrderIntent
from trading_system.strategy.signals import Signal


class RiskLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_risk_per_trade: float = Field(gt=0)
    max_daily_loss: float = Field(gt=0)
    max_open_positions: int = Field(ge=1)
    max_symbol_exposure: int = Field(default=1, ge=1)
    max_consecutive_losses: int = Field(ge=1)
    max_spread_points: int = Field(ge=1)
    max_slippage_points: int = Field(ge=0)
    max_trades_per_day: int = Field(ge=1)

    @classmethod
    def from_settings(cls, s: Settings) -> RiskLimits:
        # Settings already enforced the hard ceilings at startup.
        return cls(
            max_risk_per_trade=s.max_risk_per_trade,
            max_daily_loss=s.max_daily_loss,
            max_open_positions=s.max_open_positions,
            max_consecutive_losses=s.max_consecutive_losses,
            max_spread_points=s.max_spread_points,
            max_slippage_points=s.max_slippage_points,
            max_trades_per_day=s.max_trades_per_day,
        )


class ExposureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    open_positions: tuple[Position, ...]
    realized_pnl_today: float
    unrealized_pnl: float
    consecutive_losses: int = Field(ge=0)
    trades_today: int = Field(ge=0)
    day_start_equity: float = Field(gt=0)


class RiskDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    approved: bool
    intent: OrderIntent | None = None
    rejections: tuple[str, ...] = ()
    risk_percent: float | None = None

    @model_validator(mode="after")
    def _consistent(self) -> RiskDecision:
        if self.approved and self.intent is None:
            raise ValueError("an approved decision must carry an intent")
        if not self.approved and (self.intent is not None or not self.rejections):
            raise ValueError("a rejected decision carries no intent and must list rejections")
        return self


class BreakerState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    is_open: bool  # open = new trades blocked
    reason: str | None = None
    source: str | None = None
    since: AwareDatetime | None = None


class RiskEngine(Protocol):
    def evaluate(
        self,
        signal: Signal,
        account: AccountInfo,
        spec: SymbolSpec,
        tick: Tick,
        exposure: ExposureSnapshot,
    ) -> RiskDecision: ...


class CircuitBreaker(Protocol):
    def is_open(self) -> bool: ...
    def trip(self, reason: str, source: str) -> None: ...
    def reset(self, operator: str, reason: str) -> None:
        """Manual only, never called automatically. Requires who and why."""
        ...

    def state(self) -> BreakerState: ...
