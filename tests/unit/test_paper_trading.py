"""Paper trading (ADR 0016): parity with the backtest engine, freshness, idempotency."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trading_system.backtest.costs import CostModel
from trading_system.backtest.engine import Backtest, BacktestConfig, symbol_spec
from trading_system.backtest.trend_suite import _limits
from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.domain import Timeframe
from trading_system.storage.paper_store import PaperStore
from trading_system.strategy.baseline import BaselineParams
from trading_system.strategy.trend_breakout import TrendBreakoutParams, TrendBreakoutStrategy
from trading_system.workers.paper_loop import PaperConfig, PaperTrader, frozen_params

SYM = "XAUUSD"
H4 = timedelta(hours=4)
T0 = datetime(2024, 1, 1, tzinfo=UTC)
SPREAD = 0.30  # 30 points, the cost model
NO_SLIP = CostModel(slippage_by_symbol={SYM: 0.0}, slippage_points=0.0)
PARAMS = TrendBreakoutParams(version="paper-test", ema_fast=5, ema_slow=20, entry_window=10,
                             exit_window=5)


def trending_bars(n: int, seed: int = 7) -> list[Bar]:
    """Continuous series (open = previous close) with alternating trend phases."""
    rng = random.Random(seed)  # noqa: S311 - reproducible test data, not cryptography
    bars, close = [], 2000.0
    for i in range(n):
        drift = 3.0 if (i // 120) % 2 == 0 else -3.0
        open_ = close
        close = max(100.0, open_ + drift + rng.gauss(0, 12))
        high = max(open_, close) + abs(rng.gauss(0, 6))
        low = min(open_, close) - abs(rng.gauss(0, 6))
        bars.append(Bar(time=T0 + H4 * i, open=open_, high=high, low=low, close=close,
                        tick_volume=1, spread_points=30))
    return bars


class FakeMarket:
    """MT5 as seen right after bar k-1 closed: the tick bid is bar k's open."""

    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.k = 0
        self.reopen = timedelta(0)  # market closed this long after the bar close (daily break)
        self.delay = timedelta(minutes=1)  # run this long after trading resumed
        self.tick_lag = timedelta(0)  # simulates an out-of-sync terminal

    def resume(self) -> datetime:
        return self.bars[self.k - 1].time + H4 + self.reopen

    def now(self) -> datetime:
        return self.resume() + self.delay

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        return symbol_spec(symbol, self.bars[self.k - 1].close)

    def closed_bars(self, symbol: str, tf: Timeframe, count: int) -> list[Bar]:
        if tf is Timeframe.M1:  # first minute after the reopen, once it has closed
            if self.delay < timedelta(minutes=1):
                return []
            price = self.bars[self.k - 1].close
            # Continuous market: there were also traded minutes before the close.
            times = [self.resume()] if self.reopen else [self.resume() - timedelta(minutes=30),
                                                         self.resume()]
            return [Bar(time=t, open=price, high=price, low=price, close=price, tick_volume=1,
                        spread_points=30) for t in times]
        visible = self.bars[:self.k]
        if self.tick_lag:
            visible = [b for b in visible if b.time + H4 <= self.now() - self.tick_lag]
        return visible[-count:]

    def last_tick(self, symbol: str) -> Tick:
        bid = self.bars[self.k].open if self.k < len(self.bars) else self.bars[-1].close
        return Tick(time=self.now(), bid=bid, ask=bid + SPREAD, spread_points=30)


def trader(market: FakeMarket, store: PaperStore, **cfg: object) -> PaperTrader:
    config = PaperConfig(volume_cap=1_000.0, **cfg)  # type: ignore[arg-type]
    return PaperTrader(market, store, clock=market.now, config=config, params=PARAMS,
                       costs=NO_SLIP)


def engine_trades(bars: list[Bar], start: datetime, end: datetime) -> list[tuple[object, ...]]:
    strategy = TrendBreakoutStrategy(PARAMS, {SYM: bars})
    cfg = BacktestConfig(symbols=(SYM,), start=start, end=end, initial_equity=17_500.0,
                         costs=NO_SLIP, strategy=BaselineParams(timeframe=Timeframe.H4),
                         limits=_limits())
    bt = Backtest(cfg, {SYM: bars}, decider=strategy.decide, exit_check=strategy.exit_check,
                  stop_update=strategy.stop_update, snapshots=False)
    return [_key(t.side, t.volume, t.entry_price, t.exit_price, t.exit_reason, t.pnl)
            for t in bt.run().trades if t.exit_reason != "end_of_data"]


def _key(side: str, volume: float, entry: float, exit_: float, reason: str | None,
         pnl: float | None) -> tuple[object, ...]:
    return (side, round(volume, 2), round(entry, 6), round(exit_, 6), reason,
            round(pnl or 0.0, 2))


class TestParityWithBacktest:
    def test_bar_by_bar_paper_reproduces_the_engine(self) -> None:
        bars = trending_bars(700)
        market, store = FakeMarket(bars), PaperStore(":memory:")
        paper = trader(market, store)
        first = 60
        for k in range(first, len(bars)):  # bar k-1 just closed; bar k has opened
            market.k = k
            paper.tick()
        expected = engine_trades(bars, start=bars[first].time, end=bars[-1].time)
        got = [_key(t.intent.side, t.intent.volume, t.entry_price, t.exit_price or 0.0,
                    t.exit_reason, t.pnl) for t in store.trades("closed")]
        assert len(expected) >= 5, "fixture must produce trades"
        assert got == expected
        assert store.get("balance") == pytest.approx(17_500.0 + sum(e[5] for e in expected))

    def test_parity_holds_when_every_close_falls_in_a_market_break(self) -> None:
        bars = trending_bars(700)
        market, store = FakeMarket(bars), PaperStore(":memory:")
        market.reopen = timedelta(hours=1)  # like the 21:00 UTC gold break
        paper = trader(market, store)
        for k in range(60, len(bars)):
            market.k = k
            paper.tick()
        expected = engine_trades(bars, start=bars[60].time, end=bars[-1].time)
        got = [_key(t.intent.side, t.intent.volume, t.entry_price, t.exit_price or 0.0,
                    t.exit_reason, t.pnl) for t in store.trades("closed")]
        assert got == expected
        assert not any(s["outcome"] == "missed_late" for s in store.signals())

    def test_frozen_params_are_the_gate_a_rule(self) -> None:
        p = frozen_params()
        assert (p.version, p.timeframe, p.exit_mode, p.trend_filter) == (
            "trendbo-xau-h4-channel", Timeframe.H4, "channel", True)
        assert (p.ema_fast, p.ema_slow, p.entry_window, p.exit_window, p.stop_atr) == (
            50, 200, 20, 10, 2.0)


class TestReport:
    def test_parity_report_matches_on_time_paper(self) -> None:
        from trading_system.workers import paper_report

        bars = trending_bars(700)
        market, store = FakeMarket(bars), PaperStore(":memory:")
        paper = trader(market, store)
        for k in range(60, len(bars)):
            market.k = k
            paper.tick()
        out = paper_report.parity(store, bars[:-1], PARAMS, 17_500.0)
        assert out["status"] == "ok"
        assert len(out["trades"]) >= 5
        s = paper_report.summary(store)
        assert s["closed_trades"] == len(store.trades("closed"))
        assert s["fill_spread_points_median"] == 30

    def test_parity_flags_an_unexplained_trade(self) -> None:
        from trading_system.workers import paper_report

        bars = trending_bars(700)
        market, store = FakeMarket(bars), PaperStore(":memory:")
        paper = trader(market, store)
        for k in range(60, len(bars)):
            market.k = k
            paper.tick()
        other = PARAMS.model_copy(update={"entry_window": 7})  # engine sees other signals
        assert paper_report.parity(store, bars[:-1], other, 17_500.0)["status"] == "MISMATCH"


class TestRunControl:
    def test_first_run_only_starts(self) -> None:
        bars = trending_bars(100)
        market, store = FakeMarket(bars), PaperStore(":memory:")
        market.k = 80
        assert trader(market, store).tick().status == "started"
        assert store.get("last_bar_time") == bars[79].time.isoformat()
        assert store.signals() == []

    def test_rerun_on_the_same_bar_is_idle(self) -> None:
        bars = trending_bars(100)
        market, store = FakeMarket(bars), PaperStore(":memory:")
        paper = trader(market, store)
        market.k = 80
        paper.tick()
        market.k = 81
        assert paper.tick().status == "processed"
        assert paper.tick().status == "idle"
        assert len(store.signals()) == 1

    def test_closed_market_waits_for_the_reopen(self) -> None:
        bars = trending_bars(100)
        market, store = FakeMarket(bars), PaperStore(":memory:")
        paper = trader(market, store)
        market.k = 80
        paper.tick()
        market.k, market.reopen, market.delay = 81, timedelta(hours=1), timedelta(0)
        assert paper.tick().status == "waiting_market"  # break: no M1 bar after the close
        assert store.get("last_bar_time") == bars[79].time.isoformat()
        market.delay = timedelta(minutes=2)
        assert paper.tick().status == "processed"
        assert store.signals()[-1]["outcome"] != "missed_late"

    def test_weekend_reopen_is_not_stale_data(self) -> None:
        bars = trending_bars(100)
        market, store = FakeMarket(bars), PaperStore(":memory:")
        paper = trader(market, store)
        market.k = 80
        paper.tick()
        market.k, market.reopen, market.delay = 81, timedelta(hours=49), timedelta(minutes=3)
        assert paper.tick().status == "processed"  # Friday close decided at Sunday's reopen
        assert store.signals()[-1]["outcome"] != "missed_late"

    def test_stale_terminal_decides_nothing(self) -> None:
        bars = trending_bars(100)
        market, store = FakeMarket(bars), PaperStore(":memory:")
        paper = trader(market, store)
        market.k = 80
        paper.tick()
        market.k = 90
        market.tick_lag = H4 * 3  # MT5 still serves bars from 3 bars ago
        out = paper.tick()
        assert out.status == "stale_data"
        assert store.get("last_bar_time") == bars[79].time.isoformat()

    def test_late_processing_records_missed_entries(self) -> None:
        bars = trending_bars(700)
        market, store = FakeMarket(bars), PaperStore(":memory:")
        paper = trader(market, store)
        market.k = 60
        paper.tick()
        market.k = len(bars) - 1
        market.delay = timedelta(minutes=1)
        paper.tick()  # hundreds of bars at once: only the last one is on time
        outcomes = {s["outcome"] for s in store.signals()[:-1]}
        assert "missed_late" in outcomes
        assert "filled" not in outcomes

    def test_state_survives_a_restart(self, tmp_path: Path) -> None:
        bars = trending_bars(300)
        market, db = FakeMarket(bars), tmp_path / "paper.db"
        market.k = 60
        trader(market, PaperStore(db)).tick()
        for k in range(61, 200):
            market.k = k
            trader(market, PaperStore(db)).tick()  # a new process every run
        store = PaperStore(db)
        assert store.get("last_bar_time") == bars[198].time.isoformat()
        assert len(store.signals()) == 199 - 60
        assert len(store.trades("open")) <= 1
