"""ADR 0011, translation check: the first 10 fibsr-xau-v001 entries, cut at the entry bar.

No backtest and no outcome: only what the rules saw up to the trigger, for the partner to
say whether he would have taken each trade. Data stops before the hold-out.
  python research\\lab\\fibsr_review.py [datasets_dir]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from trading_system.backtest.walk_forward import add_months
from trading_system.broker.contracts import Bar
from trading_system.broker.history import read_bars
from trading_system.strategy.fib_sr import FibSrParams, FibSrStrategy, Setup

WARMUP = datetime(2015, 7, 1, tzinfo=UTC)
START = datetime(2016, 1, 1, tzinfo=UTC)
OUT = Path("research/reports/fibsr_review.json")  # local only (ADR 0001 #14)
N = 10


def _load(data: Path, tf: str) -> list[Bar]:
    [path] = sorted(data.glob(f"XAUUSD_{tf}_*.parquet"))[-1:]
    return read_bars(path, since=WARMUP)


def _ohlc(bars: list[Bar]) -> list[list[float | str]]:
    return [[b.time.isoformat(), b.open, b.high, b.low, b.close] for b in bars]


def main() -> int:
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("research/datasets")
    m5, h1 = _load(data, "M5"), _load(data, "H1")
    holdout = add_months(min(m5[-1].time, h1[-1].time), -12)
    m5 = [b for b in m5 if b.time < holdout]
    h1 = [b for b in h1 if b.time < holdout]
    strategy = FibSrStrategy(FibSrParams(), {"XAUUSD": m5}, {"XAUUSD": h1})
    setups = sorted((t, s) for (_, t), s in strategy._setups.items() if t >= START)
    by_year = Counter(t.year for t, _ in setups)
    print(f"setups {len(setups)} (LONG {sum(s.side.value == 'LONG' for _, s in setups)}, "
          f"SHORT {sum(s.side.value == 'SHORT' for _, s in setups)}); by year {dict(by_year)}")
    print("hold counts:", dict(strategy.hold_counts))
    # One review item per distinct leg: its first trigger (later ones repeat the same trade).
    firsts: dict[tuple[datetime, datetime], tuple[datetime, Setup]] = {}
    for t, s in setups:
        firsts.setdefault((s.leg.start_time, s.leg.end_time), (t, s))
    legs = sorted(firsts.values(), key=lambda ts: ts[0])
    print(f"distinct legs {len(legs)}; by year {dict(Counter(t.year for t, _ in legs))}")
    review = []
    for t, s in legs[:N]:
        entry_close = t + timedelta(minutes=5)
        h1_from = s.leg.start_time - timedelta(days=3)
        review.append({
            "trigger_bar": t.isoformat(), "side": s.side.value, "stop": s.stop,
            "target": s.target, "level": s.level,
            "leg": {"start_time": s.leg.start_time.isoformat(),
                    "start_price": s.leg.start_price,
                    "end_time": s.leg.end_time.isoformat(), "end_price": s.leg.target,
                    "band": [s.leg.band_lo, s.leg.band_hi]},
            "h1": _ohlc([b for b in h1 if h1_from <= b.time and
                         b.time + timedelta(hours=1) <= entry_close]),
            "m5": _ohlc([b for b in m5 if t - timedelta(hours=8) <= b.time <= t]),
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"setups": len(setups), "legs": len(legs), "by_year": by_year,
                               "review": review}, indent=1), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
