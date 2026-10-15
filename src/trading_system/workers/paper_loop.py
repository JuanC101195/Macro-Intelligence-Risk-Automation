"""Paper trading tick for `trendbo-xau-h4-channel` (ADR 0016).

Idempotent: each run processes only the H4 bars that closed since the last processed one,
in the backtest engine's order (stop/target inside the bar, channel exit at the close,
strategy stop, decision at the close). One bar = one transaction.

- Fresh-data check: if another bar should already have closed according to the tick, MT5 is
  out of sync (it happens right after the terminal starts): nothing is decided.
- A bar processed within `prompt_window` of its close trades at the real tick. Later (PC
  off) an entry is recorded as missed and a channel exit is booked at the bar close with
  the cost-model spread, exactly like the backtest.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from trading_system.backtest.costs import CostModel
from trading_system.backtest.engine import (
    LEVERAGE,
    BacktestQuotes,
    pnl_money,
    point_size,
    symbol_spec,
)
from trading_system.backtest.fills import Exit, check_exit
from trading_system.backtest.trend_suite import _limits, version_name
from trading_system.broker.contracts import (
    AccountInfo,
    Bar,
    MarketDataSource,
    Position,
    SymbolSpec,
    Tick,
)
from trading_system.domain import TIMEFRAME_MINUTES, Side, Timeframe
from trading_system.execution.paper_executor import PaperExecutor
from trading_system.macro.macro_context import MacroContext
from trading_system.risk.contracts import BreakerState, ExposureSnapshot, RiskLimits
from trading_system.risk.engine import DefaultRiskEngine
from trading_system.risk.exposure import trading_day_start
from trading_system.storage.paper_store import PaperStore, PaperTrade
from trading_system.strategy.signals import MarketState
from trading_system.strategy.trend_breakout import TrendBreakoutParams, TrendBreakoutStrategy

RunStatus = Literal["started", "processed", "idle", "waiting_market", "stale_data", "error"]


@dataclass(frozen=True)
class PaperConfig:
    symbol: str = "XAUUSD"
    capital: float = 17_500.0  # cent-account units = 175 USD (ADR 0005)
    volume_cap: float = 0.05  # ADR 0015 proportional policy
    history_bars: int = 3_000  # EMA 200 converges like in the long backtest
    prompt_window: timedelta = timedelta(minutes=15)


def frozen_params() -> TrendBreakoutParams:
    """The rule that passed Gate A (ADR 0014), unchanged."""
    return TrendBreakoutParams(version=version_name(Timeframe.H4, "channel", True),
                               timeframe=Timeframe.H4, exit_mode="channel", trend_filter=True)


@dataclass(frozen=True)
class TickOutcome:
    status: RunStatus
    bars: int = 0
    detail: str = ""


class StoreBreaker:
    """Circuit breaker persisted in the paper store (survives restarts)."""

    def __init__(self, store: PaperStore, clock: Callable[[], datetime]) -> None:
        self._store = store
        self._now = clock

    def is_open(self) -> bool:
        return self.state().is_open

    def state(self) -> BreakerState:
        raw = self._store.get("breaker")
        return BreakerState.model_validate(raw) if raw else BreakerState(is_open=False)

    def trip(self, reason: str, source: str) -> None:
        if not self.is_open():
            state = BreakerState(is_open=True, reason=reason, source=source, since=self._now())
            self._store.set("breaker", state.model_dump(mode="json"))

    def reset(self, operator: str, reason: str) -> None:
        self._store.set("breaker", BreakerState(is_open=False).model_dump(mode="json"))
        self._store.record_run(self._now(), "breaker_reset", f"{operator}: {reason}")


class PaperTrader:
    def __init__(self, market: MarketDataSource, store: PaperStore,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 config: PaperConfig | None = None, params: TrendBreakoutParams | None = None,
                 costs: CostModel | None = None, limits: RiskLimits | None = None) -> None:
        self.market = market
        self.store = store
        self.now = clock
        self.cfg = config or PaperConfig()
        self.params = params or frozen_params()
        self.costs = costs or CostModel()
        self.tf = timedelta(minutes=TIMEFRAME_MINUTES[self.params.timeframe])
        self.breaker = StoreBreaker(store, clock)
        self.risk = DefaultRiskEngine(limits or _limits(), self.breaker, BacktestQuotes(),
                                      mode="paper")
        self.executor = PaperExecutor(store, market, pnl_money, self.costs.commission, clock)

    # --- entry point --------------------------------------------------------------------

    def tick(self) -> TickOutcome:
        sym = self.cfg.symbol
        bars = self.market.closed_bars(sym, self.params.timeframe, self.cfg.history_bars)
        quote = self.market.last_tick(sym)
        now = self.now()
        if not bars:
            return self._run(now, "error", detail="no closed bars")
        last = bars[-1]
        m1 = self.market.closed_bars(sym, Timeframe.M1, 180)
        missing = self._missing_slot(last, m1, now)
        if missing is not None:
            return self._run(now, "stale_data",
                             detail=f"last closed bar {last.time:%Y-%m-%d %H:%M}, traded "
                                    f"minutes in the closed bar {missing:%Y-%m-%d %H:%M}")
        done = self.store.get("last_bar_time")
        if done is None:
            return self._start(now, last)
        new = [b for b in bars if b.time > datetime.fromisoformat(done)]
        resume = self._resume_time(new[-1].time + self.tf, m1) if new else None
        if new and resume is None:  # market closed since that close: decide after the reopen
            new = new[:-1]  # ADR 0016 addendum 1
            if not new:
                self.store.set("last_run", now.isoformat())
                return TickOutcome("waiting_market")
        if not new:
            self.store.set("last_run", now.isoformat())
            return TickOutcome("idle")
        strategy = TrendBreakoutStrategy(self.params, {sym: bars})
        for bar in new:
            prompt = resume is not None and self._prompt(bar, new, resume, now)
            with self.store.transaction():
                self._process(bar, strategy, quote, prompt=prompt, now=now)
        return self._run(now, "processed", len(new),
                         f"{new[0].time:%m-%d %H:%M}..{new[-1].time:%m-%d %H:%M}")

    def _start(self, now: datetime, last: Bar) -> TickOutcome:
        with self.store.transaction():
            self.store.set("last_bar_time", last.time.isoformat())
            self.store.set("balance", self.cfg.capital)
            self.store.set("started_at", now.isoformat())
            self.store.set("first_bar_time", last.time.isoformat())
            self.store.set("strategy", self.params.model_dump(mode="json"))
            self.store.set("config", {"symbol": self.cfg.symbol, "capital": self.cfg.capital,
                                      "volume_cap": self.cfg.volume_cap})
        return self._run(now, "started", detail=f"from bar {last.time:%Y-%m-%d %H:%M}")

    def _run(self, now: datetime, status: RunStatus, bars: int = 0,
             detail: str = "") -> TickOutcome:
        self.store.record_run(now, status, detail)
        self.store.set("last_run", now.isoformat())
        return TickOutcome(status, bars, detail)

    def _prompt(self, bar: Bar, new: Sequence[Bar], resume: datetime, now: datetime) -> bool:
        """On time = the newest bar, processed within the window after trading resumed."""
        return (bar is new[-1] and resume >= bar.time + self.tf
                and now - resume <= self.cfg.prompt_window)

    @staticmethod
    def _resume_time(close_time: datetime, m1: Sequence[Bar]) -> datetime | None:
        """Open of the first M1 bar after `close_time`; None while the market is closed."""
        return next((b.time for b in m1 if b.time >= close_time), None)

    def _missing_slot(self, last: Bar, m1: Sequence[Bar], now: datetime) -> datetime | None:
        """Start of a CLOSED H4 slot after `last` with traded minutes, i.e. a bar MT5 should
        already serve (out-of-sync terminal). Weekends and breaks have no traded minutes."""
        for minute in m1:
            slot = last.time + ((minute.time - last.time) // self.tf) * self.tf
            if slot > last.time and slot + self.tf <= now:
                return slot
        return None

    # --- one closed bar (engine order) --------------------------------------------------

    def _process(self, bar: Bar, strategy: TrendBreakoutStrategy, quote: Tick, *,
                 prompt: bool, now: datetime) -> None:
        close_time = bar.time + self.tf
        self._roll_day(close_time, bar.close)
        self._check_exit(bar, close_time)
        self._signal_exit(bar, strategy, close_time, prompt)
        self._move_stop(bar, strategy)
        self._decide(bar, strategy, quote, close_time, prompt, now)
        self.store.record_bar(bar.time, bar.open, bar.high, bar.low, bar.close)
        self.store.set("last_bar_time", bar.time.isoformat())

    def _roll_day(self, now: datetime, price: float) -> None:
        day = trading_day_start(now).isoformat()
        if self.store.get("day_start") == day:
            return
        self.store.set("day_start", day)
        self.store.set("day_start_equity", self._equity(price))
        self.store.set("realized_today", 0.0)
        self.store.set("trades_today", 0)
        if self.breaker.is_open():  # same simulated operator review as the backtest
            self.breaker.reset("paper-operator", "new trading day")
            self.store.set("consecutive_losses", 0)

    def _position(self) -> PaperTrade | None:
        open_ = self.store.trades("open")
        return open_[0] if open_ else None

    def _check_exit(self, bar: Bar, close_time: datetime) -> None:
        pos = self._position()
        if pos is None or pos.entry_time >= close_time:
            return
        point = point_size(self.cfg.symbol)
        spread = self.costs.spread(self.cfg.symbol) * point
        hit = check_exit(pos.intent.side, pos.stop, pos.intent.take_profit, bar, spread)
        if hit is None:
            return
        if hit.reason != "take_profit":  # stops are market orders: they slip
            slip = self.costs.slippage(self.cfg.symbol) * point
            hit = Exit(hit.price + (-slip if pos.intent.side == "buy" else slip), hit.reason)
        self.executor.close_at(pos.ticket, hit.price, close_time, hit.reason)
        self._book_close(pos.ticket)

    def _signal_exit(self, bar: Bar, strategy: TrendBreakoutStrategy, close_time: datetime,
                     prompt: bool) -> None:
        pos = self._position()
        if pos is None or not strategy.exit_check(self.cfg.symbol, bar, pos.intent.side):
            return
        if prompt:
            self.executor.close(pos.ticket, "signal_exit")
        else:
            point = point_size(self.cfg.symbol)
            slip = self.costs.slippage(self.cfg.symbol) * point
            spread = self.costs.spread(self.cfg.symbol) * point
            price = bar.close - slip if pos.intent.side == "buy" else bar.close + spread + slip
            self.executor.close_at(pos.ticket, price, close_time, "signal_exit", late=True)
        self._book_close(pos.ticket)

    def _move_stop(self, bar: Bar, strategy: TrendBreakoutStrategy) -> None:
        pos = self._position()
        if pos is None:
            return
        new = strategy.stop_update(self.cfg.symbol, bar, pos.intent.side, pos.entry_time,
                                   pos.entry_price, pos.intent.stop_loss, pos.stop)
        if new is not None and (new > pos.stop if pos.intent.side == "buy" else new < pos.stop):
            self.store.update_stop(pos.ticket, new)

    def _decide(self, bar: Bar, strategy: TrendBreakoutStrategy, quote: Tick,
                close_time: datetime, prompt: bool, now: datetime) -> None:
        sym = self.cfg.symbol
        tick = quote if prompt else self._model_tick(bar, close_time)
        spec = self._spec(bar.close)
        state = MarketState(has_open_position=self._position() is not None,
                            risk_blocked=self.breaker.is_open())
        signal = strategy.decide(None, bar, tick, spec, MacroContext.unknown(close_time), state,
                                 None, sym)
        if signal.side is Side.HOLD:
            self.store.record_signal(bar.time, "HOLD", "hold", ",".join(signal.hold_reasons), now)
            return
        side = signal.side.value
        if not prompt:
            late = now - close_time
            self.store.record_signal(bar.time, side, "missed_late",
                                     f"processed {late} after the close", now)
            return
        decision = self.risk.evaluate(signal, self._account(bar.close), spec, tick,
                                      self._exposure(bar.close))
        if not decision.approved or decision.intent is None:
            self.store.record_signal(bar.time, side, "rejected", ",".join(decision.rejections),
                                     now, spread_points=tick.spread_points)
            return
        result = self.executor.submit(decision.intent)
        if result.status == "filled":
            self.store.set("trades_today", int(self.store.get("trades_today") or 0) + 1)
        self.store.record_signal(bar.time, side, result.status, result.message, now,
                                 intent_id=decision.intent.intent_id,
                                 spread_points=tick.spread_points)

    # --- book keeping (mirrors the backtest engine) -------------------------------------

    def _book_close(self, ticket: int) -> None:
        trade = next(t for t in self.store.trades("closed") if t.ticket == ticket)
        pnl = trade.pnl or 0.0
        self.store.set("balance", self._balance() + pnl)
        self.store.set("realized_today", float(self.store.get("realized_today") or 0.0) + pnl)
        losses = int(self.store.get("consecutive_losses") or 0)
        self.store.set("consecutive_losses", losses + 1 if pnl < 0 else 0)

    def _model_tick(self, bar: Bar, close_time: datetime) -> Tick:
        spread_pts = self.costs.spread(self.cfg.symbol)
        return Tick(time=close_time + timedelta(seconds=2), bid=bar.close,
                    ask=bar.close + spread_pts * point_size(self.cfg.symbol),
                    spread_points=round(spread_pts))

    def _spec(self, price: float) -> SymbolSpec:
        spec = symbol_spec(self.cfg.symbol, price)
        return spec.model_copy(update={"volume_max": min(spec.volume_max, self.cfg.volume_cap)})

    def _balance(self) -> float:
        return float(self.store.get("balance"))

    def _unrealized(self, price: float) -> float:
        pos = self._position()
        if pos is None:
            return 0.0
        return pnl_money(self.cfg.symbol, pos.intent.side, pos.intent.volume, pos.entry_price,
                         price)

    def _equity(self, price: float) -> float:
        return self._balance() + self._unrealized(price)

    def _account(self, price: float) -> AccountInfo:
        equity = self._equity(price)
        pos = self._position()
        used = 0.0 if pos is None else BacktestQuotes().calc_margin(
            self.cfg.symbol, pos.intent.side, pos.intent.volume, price)
        return AccountInfo(login_masked="paper", server="paper", trade_mode="demo",
                           currency="USD", balance=self._balance(), equity=equity, margin=used,
                           margin_free=equity - used, leverage=LEVERAGE)

    def _exposure(self, price: float) -> ExposureSnapshot:
        positions: tuple[Position, ...] = tuple(self.executor.sync())
        return ExposureSnapshot(
            open_positions=positions,
            realized_pnl_today=float(self.store.get("realized_today") or 0.0),
            unrealized_pnl=self._unrealized(price),
            consecutive_losses=int(self.store.get("consecutive_losses") or 0),
            trades_today=int(self.store.get("trades_today") or 0),
            day_start_equity=max(float(self.store.get("day_start_equity") or 0.0), 1e-9),
        )
