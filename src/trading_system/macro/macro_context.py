"""Normalized macro context (CLAUDE.md §7, docs/architecture.md §5.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

RiskRegime = Literal["risk_on", "risk_off", "mixed", "unknown"]


class MacroContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: AwareDatetime
    risk_regime: RiskRegime
    confidence: float = Field(ge=0, le=1)
    vix: float | None = None
    vix_change_pct: float | None = None
    yield_curve: float | None = None
    oil_change_pct: float | None = None
    gold_change_pct: float | None = None
    credit_spread: float | None = None
    urgent_events: int = Field(default=0, ge=0)
    conflict_events: int = Field(default=0, ge=0)
    source_health: float = Field(ge=0, le=1)
    data_stale: bool

    @classmethod
    def unknown(cls, at: datetime) -> MacroContext:
        """Fallback used whenever Crucix fails or its data cannot be trusted."""
        return cls(
            timestamp=at,
            risk_regime="unknown",
            confidence=0.0,
            source_health=0.0,
            data_stale=True,
        )


class MacroProvider(Protocol):
    def current(self) -> MacroContext:
        """Must never raise: on any failure return MacroContext.unknown(...)."""
        ...

    def healthy(self) -> bool: ...
