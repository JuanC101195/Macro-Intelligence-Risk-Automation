"""PaperExecutor: the `Executor` port for paper trading (ADR 0016).

No order ever reaches the broker. Market fills use the real tick (ask to buy, bid to sell),
which the risk engine already put in `intent.entry_price`. Exits found inside a bar (stop,
take-profit, late channel exits) are booked with `close_at` at the price the backtest
engine would use, so paper and backtest stay comparable.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from trading_system.broker.contracts import MarketDataSource, Position
from trading_system.execution.order_intent import ExecutionResult, IntentMode, OrderIntent
from trading_system.storage.paper_store import PaperStore, PaperTrade

BrokerSide = Literal["buy", "sell"]
PnlFn = Callable[[str, BrokerSide, float, float, float], float]  # symbol, side, vol, entry, exit


class PaperExecutor:
    mode: IntentMode = "paper"

    def __init__(self, store: PaperStore, market: MarketDataSource, pnl: PnlFn,
                 commission: Callable[[float], float], clock: Callable[[], datetime]) -> None:
        self._store = store
        self._market = market
        self._pnl = pnl
        self._commission = commission
        self._now = clock

    def submit(self, intent: OrderIntent) -> ExecutionResult:
        if intent.mode != "paper":
            return ExecutionResult(intent_id=intent.intent_id, status="rejected",
                                   message=f"paper executor refuses mode {intent.mode}")
        if self._store.has_intent(intent.intent_id):
            return ExecutionResult(intent_id=intent.intent_id, status="duplicate",
                                   message="intent already filled")
        if self._store.trades("open"):
            return ExecutionResult(intent_id=intent.intent_id, status="rejected",
                                   message="a paper position is already open")
        tick = self._market.last_tick(intent.symbol)
        when = self._now()
        ticket = self._store.open_trade(intent, when, intent.entry_price, tick.spread_points)
        return ExecutionResult(intent_id=intent.intent_id, status="filled", broker_ticket=ticket,
                               fill_price=intent.entry_price, fill_time=when,
                               slippage_points=0.0)

    def close(self, ticket: int, reason: str) -> ExecutionResult:
        """Market close at the real tick: a buy sells at the bid, a sell buys at the ask."""
        trade = self._open(ticket)
        tick = self._market.last_tick(trade.intent.symbol)
        price = tick.bid if trade.intent.side == "buy" else tick.ask
        return self.close_at(ticket, price, self._now(), reason, tick.spread_points, late=False)

    def close_at(self, ticket: int, price: float, when: datetime, reason: str,
                 spread_points: int | None = None, late: bool = False) -> ExecutionResult:
        trade = self._open(ticket)
        i = trade.intent
        pnl = self._pnl(i.symbol, i.side, i.volume, trade.entry_price, price)
        pnl = round(pnl - self._commission(i.volume), 2)
        self._store.close_trade(ticket, exit_time=when, exit_price=price, reason=reason,
                                pnl=pnl, spread_points=spread_points, late=late)
        return ExecutionResult(intent_id=i.intent_id, status="filled", broker_ticket=ticket,
                               fill_price=price, fill_time=when,
                               commission=self._commission(i.volume), message=reason)

    def sync(self) -> list[Position]:
        return [
            Position(ticket=t.ticket, symbol=t.intent.symbol, side=t.intent.side,
                     volume=t.intent.volume, open_price=t.entry_price, stop_loss=t.stop,
                     take_profit=t.intent.take_profit, open_time=t.entry_time, profit=0.0,
                     magic=0, comment=t.intent.intent_id)
            for t in self._store.trades("open")
        ]

    def _open(self, ticket: int) -> PaperTrade:
        for trade in self._store.trades("open"):
            if trade.ticket == ticket:
                return trade
        raise KeyError(f"no open paper trade {ticket}")
