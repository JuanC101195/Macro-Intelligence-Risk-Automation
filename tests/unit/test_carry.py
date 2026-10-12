from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from trading_system.backtest.engine import Backtest, BacktestConfig, symbol_spec
from trading_system.broker.contracts import Bar, Tick
from trading_system.domain import Side, Timeframe
from trading_system.macro.macro_context import MacroContext
from trading_system.macro.rates import RateHistory, available_from
from trading_system.risk.contracts import RiskLimits
from trading_system.strategy.baseline import BaselineParams
from trading_system.strategy.carry import CarryParams, CarryStrategy
from trading_system.strategy.signals import MarketState

JAN, FEB = date(2024, 1, 1), date(2024, 2, 1)
RATES = {
    "USD": [(JAN, 5.0), (FEB, 5.0)], "EUR": [(JAN, 3.5), (FEB, 3.5)],
    "GBP": [(JAN, 5.0), (FEB, 5.2)], "JPY": [(JAN, -0.1), (FEB, 0.0)],
    "AUD": [(JAN, 4.4), (FEB, 4.4)], "CHF": [(JAN, 1.5), (FEB, 1.5)],
}
SYMBOLS = ("EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "USDCHF")
DAY = timedelta(days=1)


def daily(symbol: str, start: datetime, n: int, price: float = 1.0) -> list[Bar]:
    return [Bar(time=start + DAY * i, open=price, high=price * 1.004, low=price * 0.996,
                close=price, tick_volume=1, spread_points=0) for i in range(n)]


def strategy(**overrides: object) -> CarryStrategy:
    bars = {s: daily(s, datetime(2024, 2, 1, tzinfo=UTC), 60) for s in SYMBOLS}
    return CarryStrategy(CarryParams(**overrides), RateHistory(RATES), bars)  # type: ignore[arg-type]


def test_monthly_rate_usable_from_day_one_of_m_plus_2() -> None:
    assert available_from(JAN) == datetime(2024, 3, 1, tzinfo=UTC)
    assert available_from(date(2024, 11, 1)) == datetime(2025, 1, 1, tzinfo=UTC)
    r = RateHistory(RATES)
    assert r.rate_at("GBP", datetime(2024, 2, 28, tzinfo=UTC)) is None  # nothing usable yet
    assert r.rate_at("GBP", datetime(2024, 3, 1, tzinfo=UTC)) == 5.0  # January's value
    assert r.rate_at("GBP", datetime(2024, 4, 1, tzinfo=UTC)) == 5.2  # February's value
    assert r.differential("USDJPY", datetime(2024, 3, 2, tzinfo=UTC)) == pytest.approx(5.1)


def test_targets_top_three_by_absolute_differential() -> None:
    t = datetime(2024, 3, 5, tzinfo=UTC)
    # |d|: USDJPY 5.1, USDCHF 3.5, EURUSD 1.5, AUDUSD 0.6, GBPUSD 0.0
    assert strategy().targets(t) == {"USDJPY": Side.LONG, "USDCHF": Side.LONG,
                                     "EURUSD": Side.SHORT}
    assert set(strategy(max_positions=2).targets(t)) == {"USDJPY", "USDCHF"}
    assert strategy(threshold=4.0).targets(t) == {"USDJPY": Side.LONG}


def test_decide_only_on_rebalance_bars_with_atr_stop() -> None:
    bars = daily("USDJPY", datetime(2024, 2, 1, tzinfo=UTC), 60, 150.0)
    s = CarryStrategy(CarryParams(), RateHistory(RATES), {**{x: daily(x, bars[0].time, 60)
                                                            for x in SYMBOLS}, "USDJPY": bars})
    first_of_march = next(b for b in bars if b.time.month == 3)
    mid_march = first_of_march.time + DAY * 5
    tick = Tick(time=first_of_march.time + DAY, bid=150.0, ask=150.014, spread_points=14)
    free = MarketState(has_open_position=False, risk_blocked=False)
    macro = MacroContext.unknown(tick.time)
    sig = s.decide(None, first_of_march, tick, symbol_spec("USDJPY", 150.0), macro, free,
                   None, "USDJPY")
    assert sig.side is Side.LONG
    atr = 150.0 * 0.008  # constant true range of the synthetic bars
    assert sig.stop_loss == pytest.approx(150.014 - 3 * atr, abs=1e-3)
    later = next(b for b in bars if b.time == mid_march)
    hold = s.decide(None, later, tick, symbol_spec("USDJPY", 150.0), macro, free, None, "USDJPY")
    assert hold.hold_reasons == ("not_rebalance_bar",)


def test_exit_when_deselected_or_flipped() -> None:
    s = strategy()
    bar = next(b for b in daily("GBPUSD", datetime(2024, 2, 1, tzinfo=UTC), 60)
               if b.time.month == 3)
    assert s.exit_check("GBPUSD", bar, "buy")  # GBPUSD not selected (d = 0)
    assert not s.exit_check("USDJPY", bar, "buy")  # still the top LONG
    assert s.exit_check("USDJPY", bar, "sell")  # wrong side
    mid = bar.model_copy(update={"time": bar.time + DAY * 3})
    assert not s.exit_check("GBPUSD", mid, "buy")  # only at rebalances


def test_financing_sign_and_markup() -> None:
    s = strategy()
    t = datetime(2024, 3, 5, tzinfo=UTC)
    assert s.financing("USDJPY", "buy", t) == pytest.approx((5.1 - 1.0) / 100)
    assert s.financing("USDJPY", "sell", t) == pytest.approx((-5.1 - 1.0) / 100)


def test_engine_accrues_swap_and_exits_on_signal() -> None:
    start = datetime(2024, 3, 4, 21, 0, tzinfo=UTC)  # D1 bars open 21:00 UTC (server UTC+3)
    bars = {"USDJPY": daily("USDJPY", start, 12, 150.0)}
    entry_bar, exit_bar = bars["USDJPY"][1], bars["USDJPY"][9]

    def decider(snap, last_bar, tick, spec, macro, state, p, symbol):  # type: ignore[no-untyped-def]
        from trading_system.strategy.signals import Signal
        common = {"signal_id": "x", "symbol": symbol, "timeframe": "D1",
                  "bar_time": last_bar.time, "technical_score": 0,
                  "macro_regime": "unknown", "strategy_version": "t"}
        if last_bar.time != entry_bar.time or state.has_open_position:
            return Signal(side=Side.HOLD, confidence=0, hold_reasons=("x",), **common)
        # Stop ~1 yen away so 0.25 % risk sizes above the 0.01 lot minimum.
        return Signal(side=Side.LONG, confidence=0.5, entry_ref=tick.ask,
                      stop_loss=149.0, take_profit=155.0, **common)

    cfg = BacktestConfig(symbols=("USDJPY",), start=start, end=start + DAY * 30,
                         strategy=BaselineParams(timeframe=Timeframe.D1),
                         limits=RiskLimits(max_risk_per_trade=0.0025, max_daily_loss=0.02,
                                           max_open_positions=3, max_consecutive_losses=5,
                                           max_spread_points=30, max_slippage_points=10,
                                           max_trades_per_day=10))
    rate = 0.04  # 4 % a year in favour of the long
    bt = Backtest(cfg, bars, decider=decider,
                  exit_check=lambda s, b, side: b.time == exit_bar.time,
                  financing=lambda s, side, t: rate)
    [trade] = bt.run().trades
    assert trade.exit_reason == "signal_exit"
    held_days = (exit_bar.time + DAY - trade.entry_time).days
    expected_swap = trade.volume * 100_000 * rate * held_days / 365  # USDJPY notional in USD
    assert trade.swap == pytest.approx(expected_swap, abs=0.05)
    assert trade.pnl == pytest.approx(trade.swap + (150.0 - trade.entry_price) * trade.volume
                                      * 100_000 / 150.0 - 0.0, abs=0.05)
