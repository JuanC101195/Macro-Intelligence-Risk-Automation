"""Walk-forward optimization (ADR 0012).

Each variant is backtested once over the research period; its trades are used ONLY to
choose. For every test window, the variant with the best score on the trades CLOSED in
the previous `train_months` (and opened inside them) is chosen; the evaluated result is a
single continuous run of `Switching`, which delegates each bar to the variant chosen for
its window. A window without an eligible variant does not trade.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from trading_system.backtest.engine import ClosedTrade
from trading_system.backtest.walk_forward import add_months
from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.strategy.signals import MarketState, Signal, as_hold

Metric = Literal["expectancy_r", "profit_factor"]
Decider = Callable[..., Signal]


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    choice: str | None
    scores: dict[str, tuple[int, float | None]]  # variant -> (training trades, score)


def score(trades: Sequence[ClosedTrade], metric: Metric) -> float | None:
    rs = [t.r_multiple for t in trades]
    if not rs:
        return None
    if metric == "expectancy_r":
        return sum(rs) / len(rs)
    gains = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    return gains / losses if losses else None


def _threshold(metric: Metric) -> float:
    """A chosen variant must be better than break-even on its training trades."""
    return 0.0 if metric == "expectancy_r" else 1.0


def schedule(variant_trades: Mapping[str, Sequence[ClosedTrade]],
             windows: Sequence[tuple[datetime, datetime]], train_months: int,
             metric: Metric, min_trades: int) -> list[Window]:
    out = []
    for start, end in windows:
        train_from = add_months(start, -train_months)
        scores: dict[str, tuple[int, float | None]] = {}
        best: tuple[float, str] | None = None
        for name, trades in variant_trades.items():  # insertion order breaks ties
            seen = [t for t in trades if t.entry_time >= train_from and t.exit_time < start]
            value = score(seen, metric)
            scores[name] = (len(seen), value)
            if value is None or len(seen) < min_trades or value <= _threshold(metric):
                continue
            if best is None or value > best[0]:
                best = (value, name)
        out.append(Window(start, end, None if best is None else best[1], scores))
    return out


class Switching:
    """Decider that uses, at each bar, the variant chosen for that bar's window."""

    def __init__(self, deciders: Mapping[str, Decider], windows: Sequence[Window]) -> None:
        self.deciders = dict(deciders)
        self.windows = list(windows)
        self._starts = [w.start for w in self.windows]
        self._fallback = next(iter(self.deciders.values()))

    def choice_at(self, t: datetime) -> str | None:
        k = bisect_right(self._starts, t) - 1
        if k < 0 or t >= self.windows[k].end:
            return None
        return self.windows[k].choice

    def __call__(self, snap: Any, bar: Bar | None, tick: Tick, spec: SymbolSpec, macro: Any,
                 state: MarketState, params: Any, symbol: str) -> Signal:
        name = None if bar is None else self.choice_at(bar.time)
        if name is None:
            signal = self._fallback(snap, bar, tick, spec, macro, state, params, symbol)
            return as_hold(signal, "wfo_no_variant")
        return self.deciders[name](snap, bar, tick, spec, macro, state, params, symbol)
