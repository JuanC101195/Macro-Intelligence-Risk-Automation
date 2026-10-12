"""Event-driven multi-symbol backtest (implementation plan Phase 6).

Same decision path as live: baseline `decide()` -> DefaultRiskEngine -> OrderIntent.
Timeline: every symbol's bars are merged in time order (risk limits are portfolio-wide).
For each bar of a symbol:
  1. fill the pending order of that symbol at this bar's open (cancelled if the bar
     does not directly follow the signal bar: weekend/outage gaps are not traded through);
  2. check stop/target of its open position on this bar (fills.py rules);
  3. at the bar close, decide (strategy) and size/approve (risk). Approved orders become
     pending for the next bar's open: no look-ahead, one bar of execution delay.

Simulation assumptions (documented in the report):
- macro context is `unknown` unless a provider is given (no history before recording);
- the circuit breaker is reset by a simulated operator at the next trading day start
  (17:00 New York), together with the consecutive-loss counter.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from trading_system.backtest.costs import CostModel
from trading_system.backtest.fills import Exit, ExitReason, check_exit, entry_price
from trading_system.broker.contracts import AccountInfo, Bar, Position, SymbolSpec, Tick
from trading_system.domain import TIMEFRAME_MINUTES, Side
from trading_system.execution.order_intent import OrderIntent
from trading_system.macro.macro_context import MacroContext
from trading_system.risk.contracts import BreakerState, ExposureSnapshot, RiskLimits
from trading_system.risk.engine import DefaultRiskEngine
from trading_system.risk.exposure import trading_day_start
from trading_system.strategy.baseline import BaselineParams, decide, snapshot_series
from trading_system.strategy.signals import MarketState, Signal

CONTRACT = 100_000.0
LEVERAGE = 100
BrokerSide = Literal["buy", "sell"]


class BacktestConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbols: tuple[str, ...]
    start: datetime  # first bar (UTC) allowed to generate signals
    end: datetime  # exclusive
    initial_equity: float = 10_000.0
    costs: CostModel = CostModel()
    strategy: BaselineParams = BaselineParams()
    limits: RiskLimits
    data_hashes: dict[str, str] = {}
    label: str = ""

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


class ClosedTrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    side: BrokerSide
    signal_time: datetime
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    volume: float
    risk_amount: float
    pnl: float  # net of commission, account currency
    exit_reason: ExitReason

    @property
    def r_multiple(self) -> float:
        return self.pnl / self.risk_amount if self.risk_amount else 0.0


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[ClosedTrade]
    daily_equity: list[tuple[datetime, float]]
    hold_reasons: Counter[str]
    rejections: Counter[str]
    cancelled_fills: int
    bars_total: int
    bars_in_market: int
    final_equity: float

    def digest(self) -> str:
        payload = [t.model_dump(mode="json") for t in self.trades]
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def symbol_spec(symbol: str, price: float) -> SymbolSpec:
    """Spec for a USD account; USDJPY tick value converted at the current price."""
    jpy = symbol.endswith("JPY")
    tick = 1e-3 if jpy else 1e-5
    return SymbolSpec(
        symbol=symbol, digits=3 if jpy else 5, point=tick, tick_size=tick,
        tick_value=tick * CONTRACT / price if jpy else tick * CONTRACT,
        contract_size=CONTRACT, volume_min=0.01, volume_max=100.0, volume_step=0.01,
        stops_level_points=0, freeze_level_points=0, currency_base=symbol[:3],
        currency_profit=symbol[3:], currency_margin=symbol[:3], trade_allowed=True,
        short_allowed=True,
    )


def pnl_money(symbol: str, side: BrokerSide, volume: float, entry: float, exit_: float) -> float:
    sign = 1 if side == "buy" else -1
    raw = sign * (exit_ - entry) * volume * CONTRACT
    return raw / exit_ if symbol.endswith("JPY") else raw


class BacktestQuotes:
    """order_calc_* equivalents for a USD account at 1:100."""

    def calc_profit(self, symbol: str, side: BrokerSide, volume: float,
                    price_open: float, price_close: float) -> float:
        return pnl_money(symbol, side, volume, price_open, price_close)

    def calc_margin(self, symbol: str, side: BrokerSide, volume: float, price: float) -> float:
        if side not in ("buy", "sell"):
            raise ValueError(f"invalid side {side!r}")
        # Margin is symmetric for buys and sells on these pairs.
        notional_usd = volume * CONTRACT * (1.0 if symbol.startswith("USD") else price)
        return notional_usd / LEVERAGE


class InMemoryBreaker:
    def __init__(self) -> None:
        self._state = BreakerState(is_open=False)
        self.trips: list[str] = []
        self.resets: list[tuple[str, str]] = []

    def is_open(self) -> bool:
        return self._state.is_open

    def state(self) -> BreakerState:
        return self._state

    def trip(self, reason: str, source: str) -> None:
        if not self._state.is_open:
            self._state = BreakerState(is_open=True, reason=reason, source=source)
            self.trips.append(reason)

    def reset(self, operator: str, reason: str) -> None:
        self._state = BreakerState(is_open=False)
        self.resets.append((operator, reason))


@dataclass
class _Open:
    intent: OrderIntent
    signal_time: datetime
    entry_time: datetime
    entry: float


@dataclass
class _Pending:
    intent: OrderIntent
    signal_time: datetime
    expected_open: datetime


@dataclass
class _Book:
    balance: float
    open: dict[str, _Open] = field(default_factory=dict)
    pending: dict[str, _Pending] = field(default_factory=dict)
    last_close: dict[str, float] = field(default_factory=dict)
    day_start: datetime | None = None
    day_start_equity: float = 0.0
    realized_today: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0


class Backtest:
    def __init__(
        self,
        config: BacktestConfig,
        bars: Mapping[str, Sequence[Bar]],
        macro: Callable[[datetime], MacroContext] | None = None,
        decider: Callable[..., Signal] = decide,
    ) -> None:
        self.cfg = config
        self.bars = {s: list(bars[s]) for s in config.symbols}
        self.macro = macro or MacroContext.unknown
        self.decide = decider  # injectable for engine tests; production uses baseline decide()
        self.tf = timedelta(minutes=TIMEFRAME_MINUTES[config.strategy.timeframe])
        self.breaker = InMemoryBreaker()
        self.risk = DefaultRiskEngine(config.limits, self.breaker, BacktestQuotes(),
                                      mode="backtest")
        self.book = _Book(balance=config.initial_equity, day_start_equity=config.initial_equity)
        self.trades: list[ClosedTrade] = []
        self.daily: list[tuple[datetime, float]] = []
        self.holds: Counter[str] = Counter()
        self.rejections: Counter[str] = Counter()
        self.cancelled = 0
        self.bars_total = 0
        self.bars_in_market = 0

    def run(self) -> BacktestResult:
        snaps = {s: snapshot_series(b, self.cfg.strategy) for s, b in self.bars.items()}
        timeline = sorted(
            (bar.time, sym, i) for sym, bars in self.bars.items() for i, bar in enumerate(bars)
            if bar.time < self.cfg.end
        )
        for _, sym, i in timeline:
            self._on_bar(sym, i, snaps[sym][i])
        self._close_all_at_end()
        return BacktestResult(
            config=self.cfg, trades=self.trades, daily_equity=self.daily,
            hold_reasons=self.holds, rejections=self.rejections,
            cancelled_fills=self.cancelled, bars_total=self.bars_total,
            bars_in_market=self.bars_in_market, final_equity=self.book.balance,
        )

    # --- per bar ------------------------------------------------------------------------

    def _on_bar(self, sym: str, i: int, snap: object) -> None:
        bar = self.bars[sym][i]
        self.book.last_close[sym] = bar.close
        close_time = bar.time + self.tf
        self._roll_day(close_time)
        self._fill_pending(sym, bar)
        self._check_exit(sym, bar)
        if bar.time < self.cfg.start:
            return
        self.bars_total += 1
        if sym in self.book.open:
            self.bars_in_market += 1
        self._decide(sym, bar, close_time, snap)

    def _roll_day(self, now: datetime) -> None:
        day = trading_day_start(now)
        if self.book.day_start == day:
            return
        if self.book.day_start is not None:
            self.daily.append((self.book.day_start, self._equity()))
        self.book.day_start = day
        self.book.day_start_equity = self._equity()
        self.book.realized_today = 0.0
        self.book.trades_today = 0
        if self.breaker.is_open():  # simulated operator review at the new trading day
            self.breaker.reset("backtest-operator", "new trading day")
            self.book.consecutive_losses = 0

    def _fill_pending(self, sym: str, bar: Bar) -> None:
        pending = self.book.pending.pop(sym, None)
        if pending is None:
            return
        if bar.time != pending.expected_open:
            self.cancelled += 1  # gap after the signal bar: do not trade through it
            return
        point = 1e-3 if sym.endswith("JPY") else 1e-5
        spread = self.cfg.costs.spread(sym) * point
        slip = self.cfg.costs.slippage() * point
        price = entry_price(pending.intent.side, bar.open, spread, slip)
        self.book.open[sym] = _Open(pending.intent, pending.signal_time, bar.time, price)
        self.book.trades_today += 1

    def _check_exit(self, sym: str, bar: Bar) -> None:
        pos = self.book.open.get(sym)
        if pos is None:
            return
        point = 1e-3 if sym.endswith("JPY") else 1e-5
        spread = self.cfg.costs.spread(sym) * point
        hit = check_exit(pos.intent.side, pos.intent.stop_loss, pos.intent.take_profit, bar,
                         spread)
        if hit is None:
            return
        if hit.reason != "take_profit":  # stops are market orders: they slip
            slip = self.cfg.costs.slippage() * point
            sign = -1 if pos.intent.side == "buy" else 1
            hit = Exit(hit.price + sign * slip, hit.reason)
        self._close(sym, hit, bar.time + self.tf)

    def _decide(self, sym: str, bar: Bar, close_time: datetime, snap: object) -> None:
        point = 1e-3 if sym.endswith("JPY") else 1e-5
        spread_pts = self.cfg.costs.spread(sym)
        tick = Tick(time=close_time + timedelta(seconds=2), bid=bar.close,
                    ask=bar.close + spread_pts * point, spread_points=round(spread_pts))
        spec = symbol_spec(sym, bar.close)
        state = MarketState(has_open_position=sym in self.book.open or sym in self.book.pending,
                            risk_blocked=self.breaker.is_open())
        # decide() reports "insufficient_data" itself while the snapshot is still None.
        signal = self.decide(snap, bar, tick, spec, self.macro(close_time), state,
                             self.cfg.strategy, sym)
        if signal.side is Side.HOLD:
            self.holds.update(signal.hold_reasons)
            return
        decision = self.risk.evaluate(signal, self._account(), spec, tick, self._exposure())
        if not decision.approved or decision.intent is None:
            self.rejections.update(decision.rejections)
            return
        self.book.pending[sym] = _Pending(decision.intent, close_time, close_time)

    # --- book keeping -------------------------------------------------------------------

    def _close(self, sym: str, hit: Exit, when: datetime) -> None:
        pos = self.book.open.pop(sym)
        i = pos.intent
        pnl = pnl_money(sym, i.side, i.volume, pos.entry, hit.price)
        pnl -= self.cfg.costs.commission(i.volume)
        self.book.balance += pnl
        self.book.realized_today += pnl
        self.book.consecutive_losses = self.book.consecutive_losses + 1 if pnl < 0 else 0
        self.trades.append(ClosedTrade(
            symbol=sym, side=i.side, signal_time=pos.signal_time, entry_time=pos.entry_time,
            entry_price=pos.entry, exit_time=when, exit_price=hit.price, volume=i.volume,
            risk_amount=i.risk_amount, pnl=round(pnl, 2), exit_reason=hit.reason,
        ))

    def _close_all_at_end(self) -> None:
        while self.book.open:  # _close() removes the entry, so take one at a time
            sym = next(iter(self.book.open))
            last = self.bars[sym][-1]
            self._close(sym, Exit(self.book.last_close[sym], "end_of_data"), last.time + self.tf)
        if self.book.day_start is not None:
            self.daily.append((self.book.day_start, self._equity()))

    def _unrealized(self) -> float:
        return sum(
            pnl_money(s, p.intent.side, p.intent.volume, p.entry, self.book.last_close[s])
            for s, p in self.book.open.items()
        )

    def _equity(self) -> float:
        return self.book.balance + self._unrealized()

    def _account(self) -> AccountInfo:
        equity = self._equity()
        quotes = BacktestQuotes()
        used = sum(quotes.calc_margin(s, p.intent.side, p.intent.volume, self.book.last_close[s])
                   for s, p in self.book.open.items())
        return AccountInfo(login_masked="backtest", server="backtest", trade_mode="demo",
                           currency="USD", balance=self.book.balance, equity=equity,
                           margin=used, margin_free=equity - used, leverage=LEVERAGE)

    def _exposure(self) -> ExposureSnapshot:
        # Pending orders count as positions: otherwise two symbols approved on the same
        # bar would both fill and break max_open_positions.
        legs = [(s, p.intent, p.entry, p.entry_time) for s, p in self.book.open.items()]
        legs += [(s, p.intent, p.intent.entry_price, p.signal_time)
                 for s, p in self.book.pending.items()]
        positions = tuple(
            Position(ticket=n, symbol=s, side=intent.side, volume=intent.volume,
                     open_price=entry, stop_loss=intent.stop_loss,
                     take_profit=intent.take_profit, open_time=when, profit=0.0,
                     magic=0, comment=intent.intent_id)
            for n, (s, intent, entry, when) in enumerate(legs)
        )
        return ExposureSnapshot(
            open_positions=positions, realized_pnl_today=self.book.realized_today,
            unrealized_pnl=self._unrealized(), consecutive_losses=self.book.consecutive_losses,
            trades_today=self.book.trades_today,
            day_start_equity=max(self.book.day_start_equity, 1e-9),
        )
