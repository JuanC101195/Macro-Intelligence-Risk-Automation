"""Paper trading report and parity with the backtest (ADR 0016, gate B).

Parity re-runs the backtest engine over the same closed bars and matches trades by signal
bar. Differences in price are the real-vs-model costs being measured; a trade that only
one side has must be explained by a missed signal (PC off), otherwise it is a bug.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from trading_system.backtest.costs import CostModel
from trading_system.backtest.engine import Backtest, BacktestConfig
from trading_system.backtest.trend_suite import _limits
from trading_system.broker.contracts import Bar
from trading_system.domain import TIMEFRAME_MINUTES
from trading_system.storage.paper_store import PaperStore
from trading_system.strategy.baseline import BaselineParams
from trading_system.strategy.trend_breakout import TrendBreakoutParams, TrendBreakoutStrategy

CENTS_PER_USD = 100.0  # cent account: balance units are US cents (ADR 0005)


def summary(store: PaperStore) -> dict[str, Any]:
    signals = store.signals()
    closed = store.trades("closed")
    runs = Counter(r["status"] for r in store.runs())
    spreads = [s["spread_points"] for s in signals
               if s["outcome"] == "filled" and s["spread_points"] is not None]
    model_spread = CostModel().spread(str((store.get("config") or {}).get("symbol", "XAUUSD")))
    balance = float(store.get("balance") or 0.0)
    capital = float((store.get("config") or {}).get("capital", balance) or 0.0)
    return {
        "started_at": store.get("started_at"),
        "last_bar_time": store.get("last_bar_time"),
        "last_run": store.get("last_run"),
        "runs": dict(runs),
        "signals": dict(Counter(s["outcome"] for s in signals if s["side"] != "HOLD")),
        "hold_reasons": dict(Counter(r for s in signals if s["side"] == "HOLD"
                                     for r in s["detail"].split(",") if r)),
        "rejections": dict(Counter(r for s in signals if s["outcome"] == "rejected"
                                   for r in s["detail"].split(",") if r)),
        "open_positions": len(store.trades("open")),
        "closed_trades": len(closed),
        "late_exits": sum(t.exit_late for t in closed),
        "pnl_units": round(sum(t.pnl or 0.0 for t in closed), 2),
        "balance_units": round(balance, 2),
        "balance_usd_cent_account": round(balance / CENTS_PER_USD, 2),
        "return_pct": round((balance / capital - 1) * 100, 2) if capital else None,
        "fill_spread_points_median": statistics.median(spreads) if spreads else None,
        "fill_spread_points_max": max(spreads) if spreads else None,
        "model_spread_points": model_spread,
        "breaker": store.get("breaker"),
    }


def parity(store: PaperStore, bars: Sequence[Bar], params: TrendBreakoutParams,
           capital: float) -> dict[str, Any]:
    """Backtest over the paper period vs the paper trades, matched by signal bar time."""
    started = store.get("first_bar_time")
    if not started or not bars:
        return {"status": "no_data"}
    tf = timedelta(minutes=TIMEFRAME_MINUTES[params.timeframe])
    sym = str((store.get("config") or {}).get("symbol", "XAUUSD"))
    strategy = TrendBreakoutStrategy(params, {sym: bars})
    cfg = BacktestConfig(symbols=(sym,), start=datetime.fromisoformat(started) + tf,
                         end=bars[-1].time + tf, initial_equity=capital,
                         strategy=BaselineParams(timeframe=params.timeframe), limits=_limits())
    engine = Backtest(cfg, {sym: list(bars)}, decider=strategy.decide,
                      exit_check=strategy.exit_check, stop_update=strategy.stop_update,
                      snapshots=False).run()
    bt = {(t.signal_time - tf).isoformat(): t for t in engine.trades}
    paper = {t.signal_bar_time.isoformat(): t for t in store.trades()}
    missed = {s["bar_time"] for s in store.signals() if s["outcome"] == "missed_late"}
    rows = []
    for key in sorted(set(bt) | set(paper)):
        b, p = bt.get(key), paper.get(key)
        rows.append({
            "signal_bar": key,
            "engine": None if b is None else
            {"side": b.side, "entry": b.entry_price, "exit": b.exit_price,
             "reason": b.exit_reason, "pnl": b.pnl},
            "paper": None if p is None else
            {"side": p.intent.side, "entry": p.entry_price, "exit": p.exit_price,
             "reason": p.exit_reason, "pnl": p.pnl},
            "explained": (b is not None and p is not None and b.side == p.intent.side)
            or key in missed or (b is not None and b.exit_reason == "end_of_data"
                                 and p is None),
        })
    unexplained = [r for r in rows if not r["explained"]]
    return {"status": "ok" if not unexplained else "MISMATCH", "trades": rows,
            "unexplained": len(unexplained)}
