"""Backtest metrics (CLAUDE.md §12). All money figures are net of modelled costs."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from trading_system.backtest.engine import BacktestResult, ClosedTrade

TRADING_DAYS_PER_YEAR = 252


def session(hour_utc: int) -> str:
    if hour_utc >= 22 or hour_utc < 7:
        return "asia"
    if hour_utc < 12:
        return "london"
    if hour_utc < 16:
        return "london_ny_overlap"
    return "new_york"


def profit_factor(pnls: Iterable[float]) -> float | None:
    values = list(pnls)
    gains = sum(p for p in values if p > 0)
    losses = -sum(p for p in values if p < 0)
    if losses == 0:
        return None if gains == 0 else math.inf
    return gains / losses


def max_drawdown(equity: Sequence[float]) -> tuple[float, float]:
    """(max drawdown in money, as a fraction of the running peak)."""
    peak, worst_abs, worst_pct = -math.inf, 0.0, 0.0
    for value in equity:
        peak = max(peak, value)
        dd = peak - value
        if dd > worst_abs:
            worst_abs = dd
        if peak > 0:
            worst_pct = max(worst_pct, dd / peak)
    return worst_abs, worst_pct


def max_consecutive_losses(pnls: Iterable[float]) -> int:
    best = run = 0
    for p in pnls:
        run = run + 1 if p < 0 else 0
        best = max(best, run)
    return best


def _ratio(returns: Sequence[float], downside_only: bool) -> float | None:
    if len(returns) < 2:
        return None
    mean = statistics.fmean(returns)
    if downside_only:
        downside = [min(0.0, r) for r in returns]
        dev = math.sqrt(sum(d * d for d in downside) / len(downside))
    else:
        dev = statistics.stdev(returns)
    if dev == 0:
        return None
    return mean / dev * math.sqrt(TRADING_DAYS_PER_YEAR)


def daily_returns(daily_equity: Sequence[tuple[datetime, float]]) -> list[float]:
    values = [v for _, v in daily_equity]
    return [b / a - 1 for a, b in zip(values, values[1:], strict=False) if a > 0]


def _group(trades: Iterable[ClosedTrade], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        if key == "month":
            k = f"{t.exit_time:%Y-%m}"
        elif key == "year":
            k = f"{t.exit_time:%Y}"
        elif key == "session":
            k = session(t.entry_time.hour)
        else:
            k = getattr(t, key)
        groups[k].append(t.pnl)
    return {k: {"trades": len(v), "net": round(sum(v), 2), "profit_factor": profit_factor(v)}
            for k, v in sorted(groups.items())}


def summarize(trades: Sequence[ClosedTrade]) -> dict[str, Any]:
    """Trade-level metrics; usable on any subset (a walk-forward window, one symbol...)."""
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {
        "trades": len(pnls),
        "net_profit": round(sum(pnls), 2),
        "profit_factor": profit_factor(pnls),
        "expectancy": statistics.fmean(pnls) if pnls else None,
        "expectancy_r": statistics.fmean(t.r_multiple for t in trades) if trades else None,
        "win_rate": len(wins) / len(pnls) if pnls else None,
        "avg_win": statistics.fmean(wins) if wins else None,
        "avg_loss": statistics.fmean(losses) if losses else None,
        "max_consecutive_losses": max_consecutive_losses(pnls),
    }


def compute(result: BacktestResult) -> dict[str, Any]:
    trades = sorted(result.trades, key=lambda t: t.exit_time)
    equity_curve = [result.config.initial_equity]
    for t in trades:
        equity_curve.append(equity_curve[-1] + t.pnl)
    dd_abs, dd_pct = max_drawdown(equity_curve)
    returns = daily_returns(result.daily_equity)
    return {
        **summarize(trades),
        "initial_equity": result.config.initial_equity,
        "final_equity": round(result.final_equity, 2),
        "return_pct": result.final_equity / result.config.initial_equity - 1,
        "max_drawdown": round(dd_abs, 2),
        "max_drawdown_pct": dd_pct,
        "sharpe": _ratio(returns, downside_only=False),
        "sortino": _ratio(returns, downside_only=True),
        "time_in_market_pct": (result.bars_in_market / result.bars_total
                               if result.bars_total else 0.0),
        "by_symbol": _group(trades, "symbol"),
        "by_session": _group(trades, "session"),
        "by_month": _group(trades, "month"),
        "by_year": _group(trades, "year"),
        "exit_reasons": dict(Counter(t.exit_reason for t in trades)),
        "rejected_by_risk": dict(result.rejections.most_common()),
        "hold_reasons": dict(result.hold_reasons.most_common(10)),
        "cancelled_fills_gap": result.cancelled_fills,
    }
