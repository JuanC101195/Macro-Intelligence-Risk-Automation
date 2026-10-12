"""Persistent circuit breaker and kill switch (docs/risk-policy.md §4).

- "Open" means BLOCKED: no new trades. It never closes existing positions by itself.
- State lives in a JSON file written atomically, so it survives restarts.
- A missing file means a fresh install (closed). A file that exists but cannot be
  read or parsed means inconsistent state: the breaker starts OPEN (fail closed).
- Reset is manual only, and requires an operator name and a reason.
- Every trip and reset is appended to the history kept in the same file.
Moves to the database in Phase 7 (system_events).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_system.risk.contracts import BreakerState

KILL_SWITCH_REASON = "manual_kill"
_MAX_HISTORY = 500


class FileCircuitBreaker:
    def __init__(self, path: Path, clock: Callable[[], datetime] | None = None) -> None:
        self._path = path
        self._now = clock or (lambda: datetime.now(UTC))
        self._state, self._history = self._load()

    # --- CircuitBreaker protocol -------------------------------------------------

    def is_open(self) -> bool:
        return self._state.is_open

    def state(self) -> BreakerState:
        return self._state

    def trip(self, reason: str, source: str) -> None:
        if self._state.is_open:
            # Keep the first reason: it is the root cause. Still record the event.
            self._record("trip_ignored_already_open", reason=reason, source=source)
            return
        self._state = BreakerState(is_open=True, reason=reason, source=source, since=self._now())
        self._record("trip", reason=reason, source=source)

    def reset(self, operator: str, reason: str) -> None:
        if not operator.strip():
            raise ValueError("reset requires an operator name")
        if not reason.strip():
            raise ValueError("reset requires a reason")
        previous = self._state
        self._state = BreakerState(is_open=False)
        self._record("reset", operator=operator, reason=reason,
                     previous_reason=previous.reason, previous_source=previous.source)

    def kill(self, operator: str, reason: str) -> None:
        """Kill switch: open the breaker on behalf of a human."""
        self.trip(f"{KILL_SWITCH_REASON}: {reason}", source=f"operator:{operator}")

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    # --- persistence ------------------------------------------------------------------

    def _load(self) -> tuple[BreakerState, list[dict[str, Any]]]:
        if not self._path.exists():
            return BreakerState(is_open=False), []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return BreakerState(**data["state"]), list(data.get("history", []))
        except (OSError, ValueError, KeyError, TypeError):
            state = BreakerState(is_open=True, reason="inconsistent_state_on_startup",
                                 source="circuit_breaker", since=self._now())
            return state, [{"event": "trip", "at": self._now().isoformat(),
                            "reason": state.reason, "source": state.source}]

    def _record(self, event: str, **fields: Any) -> None:
        self._history.append({"event": event, "at": self._now().isoformat(), **fields})
        self._history = self._history[-_MAX_HISTORY:]
        self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"state": self._state.model_dump(mode="json"), "history": self._history}
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        os.replace(tmp, self._path)  # atomic on the same filesystem
