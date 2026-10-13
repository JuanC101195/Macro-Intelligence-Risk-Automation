"""Signal contract produced by strategies (docs/architecture.md §5.4).

A strategy proposes direction, entry reference and SL/TP. It never decides
volume or risk: that belongs to risk/.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.domain import Side, Timeframe, bracket_error
from trading_system.macro.macro_context import MacroContext, RiskRegime


class MarketState(BaseModel):
    """Context the strategy uses only to explain a HOLD. Risk stays the authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    has_open_position: bool
    risk_blocked: bool


class Signal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str
    symbol: str
    timeframe: Timeframe
    bar_time: AwareDatetime
    side: Side
    confidence: float = Field(ge=0, le=1)
    technical_score: int = Field(ge=0, le=100)
    reasons: tuple[str, ...] = ()
    hold_reasons: tuple[str, ...] = ()
    macro_regime: RiskRegime
    entry_ref: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy_version: str
    model_version: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Signal:
        if self.side is Side.HOLD:
            if not self.hold_reasons:
                raise ValueError("HOLD signals must say why (hold_reasons)")
            return self
        if self.entry_ref is None or self.stop_loss is None or self.take_profit is None:
            raise ValueError("LONG/SHORT signals require entry_ref, stop_loss and take_profit")
        error = bracket_error(
            self.side is Side.LONG, self.entry_ref, self.stop_loss, self.take_profit
        )
        if error:
            raise ValueError(error)
        return self


def as_hold(signal: Signal, reason: str) -> Signal:
    """The same signal turned into a HOLD (wrappers that veto an entry keep its context)."""
    if signal.side is Side.HOLD:
        return signal
    data = signal.model_dump()
    data.update(side=Side.HOLD, confidence=0.0, reasons=(), hold_reasons=(reason,),
                entry_ref=None, stop_loss=None, take_profit=None)
    return Signal(**data)


class Strategy(Protocol):
    version: str

    def evaluate(
        self,
        bars: Sequence[Bar],
        tick: Tick,
        spec: SymbolSpec,
        macro: MacroContext,
        state: MarketState,
    ) -> Signal: ...
