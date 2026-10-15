"""DemoExecutor: the `Executor` port against a MetaTrader 5 DEMO account (ADR 0024).

The only module of the package allowed to call `order_send`. Every call fails closed:
the configuration must be demo with explicit opt-in, the connected account must report
itself as demo, and the intent must be a demo intent. Orders carry `magic=MAGIC` and the
intent_id as comment, so a retry or a restart never sends the same order twice.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from trading_system.broker.contracts import AccountInfo, Deal, Position, SymbolSpec, Tick
from trading_system.config import Settings
from trading_system.domain import TradingMode
from trading_system.execution.order_intent import ExecutionResult, IntentMode, OrderIntent

MAGIC = 260_016
LOOKBACK = timedelta(days=30)
DEFAULT_DEVIATION_POINTS = 50

# MetaTrader 5 constants (duplicated so the fake terminal does not need to define them).
TRADE_ACTION_DEAL = 1
TRADE_ACTION_SLTP = 6
ORDER_TIME_GTC = 0
ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2
_TYPE = {"buy": 0, "sell": 1}

RC_DONE, RC_PLACED, RC_DONE_PARTIAL = 10009, 10008, 10010
_FILLED = {RC_DONE, RC_PLACED, RC_DONE_PARTIAL}
# Worth one retry, and only after checking the real state.
_TRANSIENT = {10012, 10024, 10031}  # timeout, too many requests, no connection

Status = Literal["filled", "rejected", "duplicate", "error", "unknown"]


class DemoBroker(Protocol):
    """What the executor needs from `Mt5Client` (a fake implements it in tests)."""

    def account_info(self) -> AccountInfo: ...
    def symbol_spec(self, symbol: str) -> SymbolSpec: ...
    def last_tick(self, symbol: str) -> Tick: ...
    def positions(self, symbol: str | None = None) -> list[Position]: ...
    def deals(self, start: datetime, end: datetime) -> list[Deal]: ...
    def filling_flags(self, symbol: str) -> int: ...
    def order_terminal(self) -> Any: ...


class DemoGuardError(Exception):
    """A safety condition failed; nothing was sent."""


def demo_guard_errors(settings: Settings, account: AccountInfo | None) -> list[str]:
    """Every reason why demo orders are NOT allowed right now (empty = allowed)."""
    errors = []
    if settings.trading_mode is not TradingMode.DEMO:
        errors.append(f"TRADING_MODE is {settings.trading_mode.value}, not demo")
    if not settings.allow_demo_orders:
        errors.append("ALLOW_DEMO_ORDERS is false")
    if settings.live_trading_enabled:
        errors.append("LIVE_TRADING_ENABLED is true")
    if account is None:
        errors.append("no account information")
    elif account.trade_mode != "demo":
        errors.append(f"connected account is {account.trade_mode}, not demo")
    return errors


def filling_type(flags: int) -> int:
    if flags & SYMBOL_FILLING_FOK:
        return ORDER_FILLING_FOK
    if flags & SYMBOL_FILLING_IOC:
        return ORDER_FILLING_IOC
    return ORDER_FILLING_RETURN


def intent_errors(intent: OrderIntent, spec: SymbolSpec, tick: Tick) -> list[str]:
    """Pre-trade checks against the live symbol spec and quote."""
    errors = []
    if intent.mode != "demo":
        errors.append(f"intent mode {intent.mode} is not demo")
    if not spec.trade_allowed or (intent.side == "sell" and not spec.short_allowed):
        errors.append("symbol not tradeable in that direction")
    if not spec.volume_min <= intent.volume <= spec.volume_max:
        errors.append(f"volume {intent.volume} outside [{spec.volume_min}, {spec.volume_max}]")
    steps = intent.volume / spec.volume_step
    if abs(steps - round(steps)) > 1e-6:
        errors.append(f"volume {intent.volume} not a multiple of {spec.volume_step}")
    price = tick.ask if intent.side == "buy" else tick.bid
    sign = 1 if intent.side == "buy" else -1
    min_gap = spec.stops_level_points * spec.point
    if sign * (price - intent.stop_loss) <= min_gap:
        errors.append("stop on the wrong side of the price or closer than the broker minimum")
    if sign * (intent.take_profit - price) <= min_gap:
        errors.append("take-profit on the wrong side of the price or too close")
    return errors


def _message(result: Any) -> str:
    """Sanitized broker answer: return code and the broker's short comment only."""
    if result is None:
        return "no answer from terminal"
    comment = str(getattr(result, "comment", ""))[:60]
    return f"retcode {getattr(result, 'retcode', '?')} {comment}".strip()


class DemoExecutor:
    mode: IntentMode = "demo"

    def __init__(self, broker: DemoBroker, settings: Settings,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 deviation_points: int = DEFAULT_DEVIATION_POINTS) -> None:
        self._broker = broker
        self._settings = settings
        self._now = clock
        self._deviation = deviation_points

    # --- Executor port ------------------------------------------------------------------

    def submit(self, intent: OrderIntent) -> ExecutionResult:
        try:
            terminal = self._guard()
        except DemoGuardError as exc:
            return self._result(intent.intent_id, "rejected", message=str(exc))
        spec = self._broker.symbol_spec(intent.symbol)
        tick = self._broker.last_tick(intent.symbol)
        errors = intent_errors(intent, spec, tick)
        if errors:
            return self._result(intent.intent_id, "rejected", message="; ".join(errors))
        known = self._find_entry(intent.intent_id)
        if known is not None:
            return self._from_deal(intent, known, "duplicate", spec, "intent already executed")
        return self._send_entry(terminal, intent, spec)

    def close(self, ticket: int, reason: str) -> ExecutionResult:
        try:
            terminal = self._guard()
        except DemoGuardError as exc:
            return self._result("", "rejected", ticket=ticket, message=str(exc))
        pos = self._own_position(ticket)
        if pos is None:
            return self._result("", "duplicate", ticket=ticket,
                                message="position already closed at the broker")
        tick = self._broker.last_tick(pos.symbol)
        side = "sell" if pos.side == "buy" else "buy"
        request = self._request(pos.symbol, side, pos.volume,
                                tick.bid if side == "sell" else tick.ask,
                                f"x:{reason}"[:31], position=ticket)
        result = self._send(terminal, request)
        if result is not None and result.retcode in _FILLED:
            return self._result(pos.comment, "filled", ticket=ticket, price=result.price,
                                message=_message(result))
        if self._own_position(ticket) is None:  # closed despite the unclear answer
            return self._result(pos.comment, "filled", ticket=ticket,
                                message="closed (confirmed by state) " + _message(result))
        status: Status = "unknown" if result is None or result.retcode in _TRANSIENT else "rejected"
        return self._result(pos.comment, status, ticket=ticket, message=_message(result))

    def modify_stop(self, ticket: int, stop_loss: float) -> ExecutionResult:
        try:
            terminal = self._guard()
        except DemoGuardError as exc:
            return self._result("", "rejected", ticket=ticket, message=str(exc))
        pos = self._own_position(ticket)
        if pos is None:
            return self._result("", "duplicate", ticket=ticket, message="position not open")
        request = {"action": TRADE_ACTION_SLTP, "symbol": pos.symbol, "position": ticket,
                   "sl": stop_loss, "tp": pos.take_profit or 0.0, "magic": MAGIC}
        result = self._send(terminal, request)
        ok = result is not None and result.retcode in _FILLED
        return self._result(pos.comment, "filled" if ok else "rejected", ticket=ticket,
                            message=_message(result))

    def sync(self) -> list[Position]:
        return [p for p in self._broker.positions() if p.magic == MAGIC]

    # --- internals ----------------------------------------------------------------------

    def _guard(self) -> Any:
        account = self._broker.account_info()
        errors = demo_guard_errors(self._settings, account)
        if errors:
            raise DemoGuardError("demo orders not allowed: " + "; ".join(errors))
        return self._broker.order_terminal()

    def _send_entry(self, terminal: Any, intent: OrderIntent, spec: SymbolSpec) -> ExecutionResult:
        for attempt in (1, 2):
            tick = self._broker.last_tick(intent.symbol)
            price = tick.ask if intent.side == "buy" else tick.bid
            request = self._request(intent.symbol, intent.side, intent.volume, price,
                                    intent.intent_id, sl=intent.stop_loss, tp=intent.take_profit)
            result = self._send(terminal, request)
            if result is not None and result.retcode in _FILLED:
                return self._filled(intent, result, spec)
            known = self._find_entry(intent.intent_id)  # unclear answer: look at the real state
            if known is not None:
                return self._from_deal(intent, known, "filled", spec,
                                       "confirmed by state after " + _message(result))
            if result is not None and result.retcode not in _TRANSIENT:
                return self._result(intent.intent_id, "rejected", message=_message(result))
            if attempt == 2:
                return self._result(intent.intent_id, "unknown",
                                    message="not confirmed after retry: " + _message(result))
        raise AssertionError("unreachable")  # pragma: no cover

    def _request(self, symbol: str, side: str, volume: float, price: float, comment: str,
                 *, sl: float = 0.0, tp: float = 0.0, position: int | None = None
                 ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "action": TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume,
            "type": _TYPE[side], "price": price, "sl": sl, "tp": tp,
            "deviation": self._deviation, "magic": MAGIC, "comment": comment,
            "type_time": ORDER_TIME_GTC,
            "type_filling": filling_type(self._broker.filling_flags(symbol)),
        }
        if position is not None:
            request["position"] = position
        return request

    @staticmethod
    def _send(terminal: Any, request: dict[str, Any]) -> Any:
        return terminal.order_send(request)

    def _find_entry(self, intent_id: str) -> Deal | None:
        now = self._now()
        for pos in self.sync():
            if pos.comment == intent_id:
                return Deal(ticket=pos.ticket, order=pos.ticket, position_id=pos.ticket,
                            symbol=pos.symbol, side=pos.side, entry="in", volume=pos.volume,
                            price=pos.open_price, time=pos.open_time, commission=0.0, swap=0.0,
                            profit=0.0, magic=pos.magic, comment=pos.comment)
        for deal in self._broker.deals(now - LOOKBACK, now + timedelta(days=1)):
            if deal.magic == MAGIC and deal.entry == "in" and deal.comment == intent_id:
                return deal
        return None

    def _own_position(self, ticket: int) -> Position | None:
        return next((p for p in self.sync() if p.ticket == ticket), None)

    def _filled(self, intent: OrderIntent, result: Any, spec: SymbolSpec) -> ExecutionResult:
        slip = (result.price - intent.entry_price) / spec.point
        if intent.side == "sell":
            slip = -slip
        return ExecutionResult(intent_id=intent.intent_id, status="filled",
                               broker_ticket=int(result.order), fill_price=float(result.price),
                               fill_time=self._now(), slippage_points=round(slip, 1),
                               message=_message(result))

    def _from_deal(self, intent: OrderIntent, deal: Deal, status: Status, spec: SymbolSpec,
                   message: str) -> ExecutionResult:
        slip = (deal.price - intent.entry_price) / spec.point * (1 if intent.side == "buy" else -1)
        return ExecutionResult(intent_id=intent.intent_id, status=status,
                               broker_ticket=deal.position_id, fill_price=deal.price,
                               fill_time=deal.time, slippage_points=round(slip, 1),
                               commission=deal.commission, message=message)

    def _result(self, intent_id: str, status: Status, *, ticket: int | None = None,
                price: float | None = None, message: str = "") -> ExecutionResult:
        return ExecutionResult(intent_id=intent_id, status=status, broker_ticket=ticket,
                               fill_price=price, fill_time=self._now() if price else None,
                               message=message)
