from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_system.backtest.engine import symbol_spec
from trading_system.backtest.trend_suite import version_name
from trading_system.broker.contracts import Bar, Tick
from trading_system.domain import Side, Timeframe
from trading_system.macro.macro_context import MacroContext
from trading_system.strategy.signals import MarketState, Signal
from trading_system.strategy.trend_breakout import TrendBreakoutParams, TrendBreakoutStrategy

H4 = timedelta(hours=4)
T0 = datetime(2024, 1, 1, tzinfo=UTC)
FREE = MarketState(has_open_position=False, risk_blocked=False)
UP = [100.0, 101, 102, 103, 104, 105, 106]


def series(closes: list[float]) -> list[Bar]:
    return [Bar(time=T0 + H4 * i, open=c, high=c + 1, low=c - 1, close=c, tick_volume=1,
                spread_points=0) for i, c in enumerate(closes)]


def make(closes: list[float], **change: object) -> tuple[TrendBreakoutStrategy, list[Bar]]:
    bars = series(closes)
    p = TrendBreakoutParams(ema_fast=2, ema_slow=4, entry_window=3, exit_window=2,
                            atr_period=2).model_copy(update=change)
    return TrendBreakoutStrategy(p, {"XAUUSD": bars}), bars


def decide(s: TrendBreakoutStrategy, bar: Bar) -> Signal:
    tick = Tick(time=bar.time + H4, bid=bar.close, ask=bar.close + 0.3, spread_points=30)
    return s.decide(None, bar, tick, symbol_spec("XAUUSD", bar.close),
                    MacroContext.unknown(tick.time), FREE, None, "XAUUSD")


class TestEntries:
    def test_long_breakout_with_the_trend(self) -> None:
        s, bars = make([*UP, 110])
        sig = decide(s, bars[-1])
        assert sig.side is Side.LONG  # 110 > max(high of previous 3) = 107, EMA2 > EMA4
        atr = s._series["XAUUSD"].atr[-1]
        assert sig.stop_loss == pytest.approx(sig.entry_ref - 2 * atr, abs=0.01)
        assert sig.take_profit == pytest.approx(sig.entry_ref + 20 * atr, abs=0.01)

    def test_target_mode_takes_profit_at_two_r(self) -> None:
        s, bars = make([*UP, 110], exit_mode="target")
        sig = decide(s, bars[-1])
        risk = sig.entry_ref - sig.stop_loss
        assert sig.take_profit == pytest.approx(sig.entry_ref + 2 * risk, abs=0.02)

    def test_breakout_against_the_trend_is_filtered(self) -> None:
        closes = [*UP, 102.5]  # below the 3-bar low (103) while EMA3 is still above EMA6
        s, bars = make(closes, ema_fast=3, ema_slow=6)
        assert s._series["XAUUSD"].trend(len(closes) - 1) == 1
        assert decide(s, bars[-1]).hold_reasons == ("against_trend",)
        control, bars = make(closes, ema_fast=3, ema_slow=6, trend_filter=False)
        assert decide(control, bars[-1]).side is Side.SHORT

    def test_no_entry_until_the_slow_ema_is_ready(self) -> None:
        s, bars = make([100.0, 101, 105])
        assert decide(s, bars[-1]).hold_reasons == ("indicators_not_ready",)
        control, bars = make([100.0, 101, 105], trend_filter=False)
        assert decide(control, bars[-1]).hold_reasons == ("indicators_not_ready",)


class TestExits:
    def test_channel_exit(self) -> None:
        s, bars = make([*UP, 103.5])
        assert not s.exit_check("XAUUSD", bars[-2], "buy")
        assert s.exit_check("XAUUSD", bars[-1], "buy")  # 103.5 < min(low of previous 2) = 104

    def test_invalidation_only_on_the_cross(self) -> None:
        closes = [*UP, 104, 101, 98, 95, 92, 90]
        s, bars = make(closes, exit_mode="invalidation")
        trend = [s._series["XAUUSD"].trend(i) for i in range(len(closes))]
        cross = next(i for i in range(1, len(closes)) if trend[i] == -1 and trend[i - 1] == 1)
        assert trend[cross + 1] == -1
        assert s.exit_check("XAUUSD", bars[cross], "buy")
        assert not s.exit_check("XAUUSD", bars[cross + 1], "buy")  # state, not a cross
        assert not s.exit_check("XAUUSD", bars[cross], "sell")

    def test_other_modes_have_no_signal_exit(self) -> None:
        s, bars = make([*UP, 104.5], exit_mode="target")
        assert not s.exit_check("XAUUSD", bars[-1], "buy")

    def test_trailing_stop_follows_the_extreme_since_entry(self) -> None:
        s, bars = make([*UP, 110, 108], exit_mode="trailing")
        atr = s._series["XAUUSD"].atr
        entry_time = bars[4].time
        stop = s.stop_update("XAUUSD", bars[-1], "buy", entry_time, 0.0, 0.0, 0.0)
        assert stop == pytest.approx(111 - 2 * atr[-1])  # highest high since entry: 110 + 1
        short = s.stop_update("XAUUSD", bars[-1], "sell", entry_time, 0.0, 0.0, 0.0)
        assert short == pytest.approx(103 + 2 * atr[-1])  # lowest low since entry: 104 - 1

    def test_no_stop_moves_outside_trailing_mode(self) -> None:
        s, bars = make([*UP, 110])
        assert s.stop_update("XAUUSD", bars[-1], "buy", bars[0].time, 0.0, 0.0, 0.0) is None


def test_version_names() -> None:
    assert version_name(Timeframe.H4, "trailing", True) == "trendbo-xau-h4-trailing"
    assert version_name(Timeframe.D1, "channel", False) == "trendbo-xau-d1-channel-nofilter"
