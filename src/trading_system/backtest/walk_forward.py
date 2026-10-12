"""Walk-forward windows (CLAUDE.md §9, ADR 0002 A6).

baseline-v001 has no fitted parameters, so every window is out-of-sample: the
walk-forward here is a set of consecutive, non-overlapping test windows over one run.
`rolling_windows` is also the splitter Phase 8 (ML) will use for train/test.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from trading_system.backtest.engine import ClosedTrade
from trading_system.backtest.metrics import summarize


def add_months(when: datetime, months: int) -> datetime:
    month = when.month - 1 + months
    return when.replace(year=when.year + month // 12, month=month % 12 + 1, day=1)


def rolling_windows(start: datetime, end: datetime, months: int) -> list[tuple[datetime, datetime]]:
    """Consecutive [start, end) windows of `months` months; the last one may be shorter."""
    if months < 1:
        raise ValueError("months must be >= 1")
    first = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    windows = []
    cursor = first
    while cursor < end:
        nxt = add_months(cursor, months)
        windows.append((max(cursor, start), min(nxt, end)))
        cursor = nxt
    return windows


def window_results(trades: Sequence[ClosedTrade], windows: Sequence[tuple[datetime, datetime]]
                   ) -> list[dict[str, Any]]:
    """Metrics per window; a trade belongs to the window where it was opened."""
    out = []
    for lo, hi in windows:
        subset = [t for t in trades if lo <= t.entry_time < hi]
        out.append({"start": lo.date().isoformat(), "end": hi.date().isoformat(),
                    **summarize(subset)})
    return out
