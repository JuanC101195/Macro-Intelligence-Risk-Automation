"""ADR 0009, prueba 1: our backtest engine against vectorbt `Portfolio.from_signals`.

breakout-h4-v001 signals, ONE instrument at a time (no portfolio limits), zero costs in both
engines (ADR 0009 addendum). Every closed trade is matched by entry bar; entry/exit bar,
reason and prices must agree. Run with the research venv:
  .venv-research\\Scripts\\python.exe research\\lab\\audit_engine.py
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import vectorbt as vbt

from trading_system.backtest import instruments
from trading_system.backtest.costs import CostModel
from trading_system.backtest.engine import Backtest, BacktestConfig
from trading_system.backtest.runner import REGIME_TRAIN_MONTHS, holdout_start, load_datasets
from trading_system.backtest.walk_forward import add_months
from trading_system.broker.contracts import Bar
from trading_system.domain import Timeframe
from trading_system.risk.contracts import RiskLimits
from trading_system.strategy.baseline import BaselineParams
from trading_system.strategy.breakout import BreakoutParams, BreakoutStrategy

DATA = Path("research/datasets")
SYMBOLS = ("XAUUSD", "XAGUSD", "US500", "US30", "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD",
           "USDJPY", "USDCAD", "USDCHF")
TF = timedelta(hours=4)
PARAMS = BreakoutParams(version="breakout-h4-v001", timeframe=Timeframe.H4)
LOOSE = RiskLimits(max_risk_per_trade=0.0025, max_daily_loss=1.0, max_open_positions=1,
                   max_consecutive_losses=1_000_000, max_spread_points=1_000_000,
                   max_slippage_points=1_000_000, max_trades_per_day=1_000_000)
ZERO = CostModel(spread_points=dict.fromkeys(SYMBOLS, 0), slippage_points=0.0,
                 slippage_by_symbol={})


def ours(sym: str, bars: list[Bar], start: Any, end: Any) -> list[Any]:
    cfg = BacktestConfig(symbols=(sym,), start=start, end=end, limits=LOOSE, costs=ZERO,
                         initial_equity=1e9,
                         strategy=BaselineParams(timeframe=Timeframe.H4, version=PARAMS.version))
    strategy = BreakoutStrategy(PARAMS, {sym: bars})
    bt = Backtest(cfg, {sym: bars}, decider=strategy.decide, exit_check=strategy.exit_check)
    return [t for t in bt.run().trades if t.exit_reason != "end_of_data"]


def theirs(sym: str, bars: list[Bar], start: Any, end: Any) -> pd.DataFrame:
    """Same rules expressed as vectorbt signals; entries shifted to the next (contiguous) open."""
    strategy = BreakoutStrategy(PARAMS, {sym: bars})
    bars = [b for b in bars if b.time < end]
    n = len(bars)
    idx = pd.DatetimeIndex([b.time for b in bars])
    o = np.array([b.open for b in bars])
    h = np.array([b.high for b in bars])
    lo = np.array([b.low for b in bars])
    c = np.array([b.close for b in bars])
    long_in, short_in = np.zeros(n, bool), np.zeros(n, bool)
    long_out, short_out = np.zeros(n, bool), np.zeros(n, bool)
    sl, tp = np.full(n, np.nan), np.full(n, np.nan)
    price = c.copy()
    for i, bar in enumerate(bars):
        lv = strategy._levels[(sym, bar.time)]
        long_out[i] = lv.exit_low is not None and bar.close < lv.exit_low
        short_out[i] = lv.exit_high is not None and bar.close > lv.exit_high
    for i, bar in enumerate(bars):
        lv = strategy._levels[(sym, bar.time)]
        side = strategy._direction(sym, bar)
        if (side is None or lv.atr is None or bar.time < start or i + 1 >= n
                or bars[i + 1].time != bar.time + TF):  # engine cancels fills across gaps
            continue
        j = i + 1  # fill bar
        if long_out[j] if side.value == "LONG" else short_out[j]:
            # vectorbt: one order and one price per bar. The engine exits at this close
            # (or does an entry-at-open/exit-at-close round trip): not expressible here.
            continue
        sign = 1 if side.value == "LONG" else -1
        digits = instruments.info(sym).digits  # the engine rounds stop/target to digits
        stop = round(bar.close - sign * PARAMS.stop_atr * lv.atr, digits)
        target = round(max(bar.close + sign * PARAMS.target_atr * lv.atr, bar.close * 0.1),
                       digits)
        (long_in if sign > 0 else short_in)[j] = True
        price[j] = o[j]
        sl[j] = abs(o[j] - stop) / o[j]
        tp[j] = abs(target - o[j]) / o[j]
    pf = vbt.Portfolio.from_signals(
        close=pd.Series(c, idx), open=pd.Series(o, idx), high=pd.Series(h, idx),
        low=pd.Series(lo, idx), price=pd.Series(price, idx),
        entries=pd.Series(long_in, idx), exits=pd.Series(long_out, idx),
        short_entries=pd.Series(short_in, idx), short_exits=pd.Series(short_out, idx),
        sl_stop=pd.Series(sl, idx), tp_stop=pd.Series(tp, idx), stop_entry_price="price",
        upon_opposite_entry="ignore",  # the engine never reverses an open position
        # An entry flag while already in position is ignored by the engine: exit wins.
        upon_long_conflict="adjacent", upon_short_conflict="adjacent",
        size=1.0, init_cash=1e12, fees=0.0, slippage=0.0, freq="4h",
    )
    trades = pf.trades.records_readable
    return trades[trades["Status"] == "Closed"]


def _convention(t: Any, bar: Bar, vb_exit: pd.Timestamp, exit_bar: pd.Timestamp) -> str | None:
    """Documented differences between the engines (not bugs), or None."""
    if vb_exit <= exit_bar or not t.exit_reason.startswith("stop"):
        return None
    if exit_bar == pd.Timestamp(t.entry_time):
        return "conv_stop_in_entry_bar"  # ours checks the stop in the fill bar, vbt does not
    touched = bar.low if t.side == "buy" else bar.high
    if touched == t.exit_price:
        return "conv_exact_touch"  # ours: touching the stop fills it (conservative)
    return None


def compare(sym: str, mine: list[Any], vb: pd.DataFrame, by_time: dict[Any, Bar]
            ) -> Counter[str]:
    result: Counter[str] = Counter()
    vb_by_entry = {row["Entry Timestamp"]: row for _, row in vb.iterrows()}
    for t in mine:
        row = vb_by_entry.pop(pd.Timestamp(t.entry_time), None)
        if row is None and t.exit_time - TF == t.entry_time:
            result["conv_same_bar_round_trip"] += 1  # one order per bar in vectorbt
            continue
        entry = pd.Timestamp(t.entry_time)
        vb_holds = (vb["Entry Timestamp"] < entry) & (vb["Exit Timestamp"] >= entry)
        if row is None and vb_holds.any():
            result["conv_cascade"] += 1  # vbt still holds a position a convention kept open
            continue
        if row is None:
            result["only_ours"] += 1
            print(f"  {sym} only ours: {t.entry_time} {t.side} -> {t.exit_time} {t.exit_reason}")
            continue
        exit_bar = pd.Timestamp(t.exit_time - TF)
        price_ok = abs(row["Avg Exit Price"] - t.exit_price) <= 1e-9 * max(1.0, t.exit_price)
        if row["Exit Timestamp"] != exit_bar:
            kind = _convention(t, by_time[t.exit_time - TF], row["Exit Timestamp"], exit_bar)
            result[kind or "exit_time"] += 1
            if kind is None:
                print(f"  {sym} exit differs: entry {t.entry_time} ours {exit_bar} "
                      f"{t.exit_reason} @{t.exit_price} | vbt {row['Exit Timestamp']} "
                      f"@{row['Avg Exit Price']}")
        elif not price_ok and t.exit_reason == "take_profit" and (
                row["Avg Exit Price"] - t.exit_price) * (1 if t.side == "buy" else -1) > 0:
            result["conv_tp_gap"] += 1  # ours fills a gapped TP at the limit (conservative)
        elif not price_ok:
            result["exit_price"] += 1
            print(f"  {sym} exit price: {t.entry_time} ours {t.exit_price} {t.exit_reason}"
                  f" | vbt {row['Avg Exit Price']}")
        elif abs(row["Avg Entry Price"] - t.entry_price) > 1e-9 * t.entry_price:
            result["entry_price"] += 1
        else:
            result["match"] += 1
    for ts in vb_by_entry:
        held = any(t.entry_time < ts.to_pydatetime() < t.exit_time for t in mine)
        result["conv_cascade" if held else "only_vbt"] += 1
        if not held:
            print(f"  {sym} only vbt: {ts}")
    return result


def main() -> int:
    bars, _ = load_datasets(DATA, list(SYMBOLS), Timeframe.H4)
    first = max(b[0].time for b in bars.values())
    start = add_months(first, REGIME_TRAIN_MONTHS)
    end = holdout_start(bars)
    total: Counter[str] = Counter()
    for sym in SYMBOLS:
        res = compare(sym, ours(sym, bars[sym], start, end), theirs(sym, bars[sym], start, end),
                      {b.time: b for b in bars[sym]})
        print(sym, dict(res))
        total.update(res)
    trades = sum(total.values())
    explained = total["match"] + sum(v for k, v in total.items() if k.startswith("conv_"))
    share = explained / trades if trades else 0.0
    print("TOTAL", dict(total))
    print(f"exact match {total['match'] / trades:.2%}; match + documented conventions "
          f"{share:.2%} (criterion >= 99%)")
    return 0 if share >= 0.99 else 1


if __name__ == "__main__":
    sys.exit(main())
