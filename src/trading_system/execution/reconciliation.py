"""Reconcile what the trading loop believes is open with the broker (ADR 0024).

- `closed_at_broker`: tickets the loop holds open that the broker no longer has (stop or
  take-profit hit, or closed by hand). The loop books them with their exit deal.
- `unknown_at_broker`: positions with our magic that the loop does not know. Never
  adopted silently: the caller opens the circuit breaker.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict

from trading_system.broker.contracts import Deal, Position


class Reconciliation(BaseModel):
    model_config = ConfigDict(frozen=True)

    closed_at_broker: tuple[int, ...] = ()
    unknown_at_broker: tuple[int, ...] = ()
    exit_deals: dict[int, Deal] = {}

    @property
    def consistent(self) -> bool:
        return not self.closed_at_broker and not self.unknown_at_broker

    @property
    def needs_breaker(self) -> bool:
        return bool(self.unknown_at_broker) or any(
            t not in self.exit_deals for t in self.closed_at_broker)


def reconcile(expected_open: Iterable[int], broker_positions: Sequence[Position],
              deals: Sequence[Deal], magic: int) -> Reconciliation:
    expected = set(expected_open)
    ours = {p.ticket for p in broker_positions if p.magic == magic}
    closed = sorted(expected - ours)
    exits = {}
    for ticket in closed:
        out = [d for d in deals if d.position_id == ticket and d.entry in ("out", "out_by")]
        if out:
            exits[ticket] = out[-1]
    return Reconciliation(closed_at_broker=tuple(closed),
                          unknown_at_broker=tuple(sorted(ours - expected)), exit_deals=exits)
