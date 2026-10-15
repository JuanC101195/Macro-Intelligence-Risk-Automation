"""Scripted broker for DemoExecutor tests (ADR 0024). No network, no MetaTrader5."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from trading_system.broker.contracts import AccountInfo, Deal, Position, SymbolSpec, Tick

NOW = datetime(2026, 10, 15, 13, 0, 5, tzinfo=UTC)

XAU_SPEC = SymbolSpec(
    symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01, tick_value=1.0, contract_size=100.0,
    volume_min=0.01, volume_max=100.0, volume_step=0.01, stops_level_points=0,
    freeze_level_points=0, currency_base="XAU", currency_profit="USD", currency_margin="XAU",
    trade_allowed=True, short_allowed=True,
)


@dataclass
class FakeTerminal:
    """`order_send` answers come from `script` (retcode int or None); executions mutate the
    broker state like a real terminal. `ghost` = execute but answer None (lost reply)."""

    broker: FakeDemoBroker
    script: list[int | None | str] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    fill_price: float | None = None

    def order_send(self, request: dict[str, Any]) -> SimpleNamespace | None:
        self.requests.append(dict(request))
        answer = self.script.pop(0) if self.script else 10009
        if answer == "ghost":
            self.broker.execute(request, self.fill_price)
            return None
        if answer in (10009, 10008, 10010):
            order = self.broker.execute(request, self.fill_price)
            return SimpleNamespace(retcode=answer, order=order, price=self._price(request),
                                   comment="Request executed")
        if answer is None:
            return None
        return SimpleNamespace(retcode=answer, order=0, price=0.0, comment="Requote")

    def _price(self, request: dict[str, Any]) -> float:
        return self.fill_price if self.fill_price is not None else request.get("price", 0.0)


@dataclass
class FakeDemoBroker:
    trade_mode: str = "demo"
    bid: float = 4000.00
    ask: float = 4000.30
    filling: int = 1  # FOK
    open_positions: list[Position] = field(default_factory=list)
    history: list[Deal] = field(default_factory=list)
    terminal_calls: int = 0
    next_ticket: int = 1000
    terminal: FakeTerminal = field(init=False)

    def __post_init__(self) -> None:
        self.terminal = FakeTerminal(self)

    # --- DemoBroker protocol -------------------------------------------------------------
    def account_info(self) -> AccountInfo:
        return AccountInfo(login_masked="****4567", server="MetaQuotes-Demo",
                           trade_mode=self.trade_mode,  # type: ignore[arg-type]
                           currency="USD", balance=10_000.0, equity=10_000.0, margin=0.0,
                           margin_free=10_000.0, leverage=100)

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        return XAU_SPEC

    def last_tick(self, symbol: str) -> Tick:
        return Tick(time=NOW, bid=self.bid, ask=self.ask,
                    spread_points=round((self.ask - self.bid) / 0.01))

    def positions(self, symbol: str | None = None) -> list[Position]:
        return list(self.open_positions)

    def deals(self, start: datetime, end: datetime) -> list[Deal]:
        return [d for d in self.history if start <= d.time <= end]

    def filling_flags(self, symbol: str) -> int:
        return self.filling

    def order_terminal(self) -> Any:
        self.terminal_calls += 1
        if self.trade_mode != "demo":
            raise AssertionError("order_terminal must not be reached for a non-demo account")
        return self.terminal

    # --- simulated execution --------------------------------------------------------------
    def execute(self, request: dict[str, Any], fill: float | None) -> int:
        price = fill if fill is not None else request.get("price", 0.0)
        side = "buy" if request.get("type") == 0 else "sell"
        if request["action"] == 6:  # SLTP
            self.open_positions = [p.model_copy(update={"stop_loss": request["sl"]})
                                   if p.ticket == request["position"] else p
                                   for p in self.open_positions]
            return request["position"]
        if "position" in request:  # closing deal
            ticket = request["position"]
            self.open_positions = [p for p in self.open_positions if p.ticket != ticket]
            self.history.append(self.deal(ticket, side, "out", price, request["comment"]))
            return ticket
        self.next_ticket += 1
        ticket = self.next_ticket
        self.open_positions.append(Position(
            ticket=ticket, symbol=request["symbol"], side=side, volume=request["volume"],
            open_price=price, stop_loss=request["sl"], take_profit=request["tp"], open_time=NOW,
            profit=0.0, magic=request["magic"], comment=request["comment"]))
        self.history.append(self.deal(ticket, side, "in", price, request["comment"],
                                      magic=request["magic"]))
        return ticket

    @staticmethod
    def deal(position: int, side: str, entry: str, price: float, comment: str,
             magic: int = 260_016) -> Deal:
        return Deal(ticket=position * 10, order=position, position_id=position, symbol="XAUUSD",
                    side=side, entry=entry, volume=0.01, price=price,  # type: ignore[arg-type]
                    time=NOW, commission=0.0, swap=0.0, profit=0.0, magic=magic, comment=comment)
