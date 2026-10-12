from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from trading_system.backtest.engine import notional_usd, pnl_money, symbol_spec
from trading_system.backtest.financing import make_financing
from trading_system.broker.contracts import Bar, Tick
from trading_system.domain import Side
from trading_system.macro.macro_context import MacroContext
from trading_system.macro.rates import RateHistory
from trading_system.risk.exposure import currency_legs
from trading_system.strategy.breakout import BreakoutParams, BreakoutStrategy
from trading_system.strategy.signals import MarketState

DAY = timedelta(days=1)
T0 = datetime(2024, 1, 1, 21, 0, tzinfo=UTC)
FREE = MarketState(has_open_position=False, risk_blocked=False)


def series(closes: list[float]) -> list[Bar]:
    return [Bar(time=T0 + DAY * i, open=c, high=c + 1, low=c - 1, close=c, tick_volume=1,
                spread_points=0) for i, c in enumerate(closes)]


class TestInstruments:
    def test_gold_pnl_and_spec(self) -> None:
        # 0.01 lot of gold = 1 oz: a 10 USD move is 10 USD.
        assert pnl_money("XAUUSD", "buy", 0.01, 2000.0, 2010.0) == pytest.approx(10.0)
        spec = symbol_spec("XAUUSD", 2000.0)
        assert spec.tick_value == pytest.approx(1.0)  # 0.01 USD x 100 oz per lot
        assert spec.volume_min == 0.01
        assert notional_usd("XAUUSD", 0.01, 2000.0) == pytest.approx(2000.0)

    def test_index_pnl_and_min_lot(self) -> None:
        assert pnl_money("US500", "sell", 0.1, 5000.0, 4950.0) == pytest.approx(5.0)
        assert symbol_spec("US500", 5000.0).volume_min == 0.1

    def test_usdcad_profit_converted(self) -> None:
        assert pnl_money("USDCAD", "buy", 1.0, 1.35, 1.36) == pytest.approx(1000 / 1.36)

    def test_unknown_cross_rejected(self) -> None:
        with pytest.raises(ValueError):
            pnl_money("EURGBP", "buy", 1.0, 0.85, 0.86)

    def test_currency_legs_only_for_six_letter_symbols(self) -> None:
        assert currency_legs("XAUUSD", "buy") == {"XAU": 1, "USD": -1}
        assert currency_legs("US500", "buy") == {}


def test_financing_by_asset_class() -> None:
    rates = RateHistory({"USD": [(date(2023, 11, 1), 5.0)], "JPY": [(date(2023, 11, 1), 0.0)]})
    f = make_financing(rates)
    t = datetime(2024, 1, 15, tzinfo=UTC)
    assert f("USDJPY", "buy", t) == pytest.approx(0.04)  # 5 - 0 - 1
    assert f("XAUUSD", "buy", t) == pytest.approx(-0.06)  # pays USD rate + 1
    assert f("US500", "sell", t) == pytest.approx(-0.01)  # pays markup, credited nothing


class TestBreakout:
    def _strategy(self, closes: list[float]) -> tuple[BreakoutStrategy, list[Bar]]:
        bars = series(closes)
        p = BreakoutParams(entry_window=5, exit_window=3, atr_period=3)
        return BreakoutStrategy(p, {"XAUUSD": bars}), bars

    def _decide(self, s: BreakoutStrategy, bar: Bar) -> object:
        tick = Tick(time=bar.time + DAY, bid=bar.close, ask=bar.close + 0.3, spread_points=30)
        return s.decide(None, bar, tick, symbol_spec("XAUUSD", bar.close),
                        MacroContext.unknown(tick.time), FREE, None, "XAUUSD")

    def test_long_on_close_above_prior_high(self) -> None:
        s, bars = self._strategy([100, 101, 102, 101, 100, 99, 104.5])
        sig = self._decide(s, bars[-1])
        assert sig.side is Side.LONG  # 104.5 > max(high of previous 5) = 103
        assert sig.stop_loss < sig.entry_ref < sig.take_profit

    def test_no_signal_inside_channel_and_current_bar_excluded(self) -> None:
        s, bars = self._strategy([100, 101, 102, 101, 100, 99, 102.5])
        assert self._decide(s, bars[-1]).hold_reasons == ("no_breakout",)

    def test_short_and_exit_rules(self) -> None:
        s, bars = self._strategy([100, 99, 98, 99, 100, 101, 95.5, 96, 97, 101.5])
        assert self._decide(s, bars[6]).side is Side.SHORT  # 95.5 < min(low of prev 5) = 97
        assert not s.exit_check("XAUUSD", bars[8], "sell")
        assert s.exit_check("XAUUSD", bars[9], "sell")  # 101.5 > max(high of prev 3) = 98

    def test_not_ready_before_window(self) -> None:
        s, bars = self._strategy([100, 101, 102])
        assert self._decide(s, bars[-1]).hold_reasons == ("no_breakout",)
