"""Two-leg engine mechanics (ADR 0007) with a scripted strategy and hand-computed prices."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from trading_system.backtest.engine import BacktestConfig
from trading_system.backtest.pairs_engine import PairBacktest
from trading_system.broker.contracts import Bar
from trading_system.domain import Timeframe
from trading_system.risk.contracts import RiskLimits
from trading_system.strategy.baseline import BaselineParams
from trading_system.strategy.pairs import PairsParams, PairState

T0 = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)  # a Wednesday
H1 = timedelta(hours=1)
LIMITS = RiskLimits(max_risk_per_trade=0.0025, max_daily_loss=0.02, max_open_positions=3,
                    max_consecutive_losses=5, max_spread_points=30, max_slippage_points=10,
                    max_trades_per_day=10)


class Scripted:
    """Long spread signal at `entry_bar`; z/time exit at `exit_bar` (common bar numbers)."""

    def __init__(self, entry_bar: int, exit_bar: int | None) -> None:
        self.params = PairsParams()
        self.entry_t = T0 + H1 * entry_bar
        self.exit_t = None if exit_bar is None else T0 + H1 * exit_bar

    def state(self, t: datetime) -> PairState:
        return PairState(index=self.index(t), beta=1.0, z=-2.5, spread_std=0.001,
                         cointegrated=True)

    def index(self, t: datetime) -> int:
        return int((t - T0) / H1)

    def atr(self, _symbol: str, _t: datetime) -> float:
        return 0.001

    def entry(self, t: datetime) -> tuple[int, str | None]:
        return (1, None) if t == self.entry_t else (0, "no_setup")

    def should_exit(self, t: datetime, _direction: int, _entry_index: int) -> bool:
        return t == self.exit_t


def flat(price: float, n: int = 8, skip: frozenset[int] = frozenset(),
         changes: dict[int, tuple[float, float, float, float]] | None = None) -> list[Bar]:
    out = []
    for i in range(n):
        if i in skip:
            continue
        o, h, lo, c = (changes or {}).get(i, (price, price + 0.0002, price - 0.0002, price))
        out.append(Bar(time=T0 + H1 * i, open=o, high=h, low=lo, close=c, tick_volume=1,
                       spread_points=0))
    return out


def run(aud: list[Bar], nzd: list[Bar], strategy: Any, limits: RiskLimits = LIMITS
        ) -> tuple[Any, PairBacktest]:
    cfg = BacktestConfig(symbols=("AUDUSD", "NZDUSD"), start=T0, end=T0 + timedelta(days=5),
                         limits=limits, initial_equity=17_500.0,
                         strategy=BaselineParams(timeframe=Timeframe.H1, version="pairs-v001"))
    bt = PairBacktest(cfg, {"AUDUSD": aud, "NZDUSD": nzd}, strategy)
    return bt.run(), bt


def test_legs_open_and_close_together_as_one_trade() -> None:
    aud = flat(0.70, changes={5: (0.70, 0.7012, 0.6998, 0.7010)})
    result, bt = run(aud, flat(0.60), Scripted(entry_bar=2, exit_bar=5))

    legs = {t.symbol: t for t in bt.leg_trades}
    a, b = legs["AUDUSD"], legs["NZDUSD"]
    # Sizing: notional A = 17,500 x 0.25% / (2 x 0.001) = 21,875 USD; both legs scaled by
    # 43.75 / (0.3646 lots x 0.004 x 100k) = 0.30 so no leg risks more than 0.25%.
    assert (a.side, a.volume, b.side, b.volume) == ("buy", 0.09, "sell", 0.10)
    assert a.entry_time == b.entry_time == T0 + H1 * 3
    assert a.entry_price == pytest.approx(0.70016)  # ask 0.70014 + 2 points slippage
    assert a.exit_price == pytest.approx(0.70098)  # close 0.7010 at the bid - slippage
    assert b.exit_price == pytest.approx(0.60020)  # close at the ask + slippage
    assert a.exit_time == b.exit_time == T0 + H1 * 6
    assert a.pnl == pytest.approx(7.38)
    assert b.pnl == pytest.approx(-2.20)

    [pair] = result.trades
    assert pair.symbol == "AUDUSD/NZDUSD"
    assert pair.pnl == pytest.approx(5.18)
    assert pair.exit_reason == "signal_exit"
    assert pair.risk_amount == pytest.approx(13.13, abs=0.01)
    assert bt.book.consecutive_losses == 0  # the losing leg alone is not a loss


def test_missing_fill_bar_of_one_leg_cancels_both() -> None:
    result, bt = run(flat(0.70), flat(0.60, skip=frozenset({3})), Scripted(2, 5))
    assert result.trades == []
    assert result.cancelled_fills == 2
    assert bt.book.pending == {} and bt.book.open == {}


def test_stopped_leg_closes_the_other_at_its_next_open() -> None:
    aud = flat(0.70, changes={4: (0.70, 0.7002, 0.6950, 0.6960)})
    result, bt = run(aud, flat(0.60), Scripted(entry_bar=2, exit_bar=None))

    legs = {t.symbol: t for t in bt.leg_trades}
    assert legs["AUDUSD"].exit_reason == "stop_loss"
    assert legs["AUDUSD"].exit_time == T0 + H1 * 5
    # Not at the open of bar 4 (that would be before the stop): at the open of bar 5.
    assert legs["NZDUSD"].exit_reason == "pair_leg_closed"
    assert legs["NZDUSD"].exit_time == T0 + H1 * 5
    [pair] = result.trades
    assert pair.exit_reason == "stop_loss"
    assert pair.pnl < 0
    assert bt.book.consecutive_losses == 1


def test_rejected_second_leg_leaves_nothing_pending() -> None:
    limits = LIMITS.model_copy(update={"max_open_positions": 1})
    result, bt = run(flat(0.70), flat(0.60), Scripted(2, 5), limits=limits)
    assert result.trades == []
    assert result.rejections["max_open_positions"] == 1
    assert bt.book.pending == {} and bt.book.open == {}
