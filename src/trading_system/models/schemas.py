"""Model registry record and the ML filter port (docs/model-policy.md)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from trading_system.domain import Timeframe
from trading_system.strategy.signals import Signal

ModelStatus = Literal["candidate", "validated", "approved", "active", "rejected", "retired"]


class ModelRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    version: str
    symbol: str
    timeframe: Timeframe
    features: tuple[str, ...]
    train_start: AwareDatetime
    train_end: AwareDatetime
    validation_start: AwareDatetime
    validation_end: AwareDatetime
    test_start: AwareDatetime
    test_end: AwareDatetime
    label_spec: Mapping[str, Any]
    metrics: Mapping[str, Any]
    costs: Mapping[str, Any]
    status: ModelStatus
    artifact_sha256: str
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def _chronological_splits(self) -> ModelRecord:
        # Time series: train must end before validation starts, validation before test.
        if not (
            self.train_start < self.train_end
            <= self.validation_start < self.validation_end
            <= self.test_start < self.test_end
        ):
            raise ValueError("splits must be chronological and non-overlapping")
        return self


class SignalFilter(Protocol):
    """ML filter. May only lower confidence or turn a signal into HOLD."""

    version: str

    def adjust(self, signal: Signal, features: Mapping[str, float]) -> Signal: ...
