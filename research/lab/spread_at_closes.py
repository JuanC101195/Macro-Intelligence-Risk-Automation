"""B4' of ADR 0017: real XAUUSD spread at the first tick after each H4 close (last 6 months).

Read-only. Run from the main checkout (needs .env):
    $env:PYTHONPATH='<checkout>\\src'; .\\.venv\\Scripts\\python.exe research\\lab\\spread_at_closes.py
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import UTC, datetime, timedelta

import MetaTrader5 as mt5  # noqa: N813

from trading_system.broker.mt5_client import Mt5Client
from trading_system.config import load_settings
from trading_system.domain import Timeframe

SYMBOL = "XAUUSD"
MONTHS = 6
MODEL_POINTS = 30
WINDOW = timedelta(minutes=5)  # first tick within 5 min of the close, else "no tick"


def main() -> int:
    client = Mt5Client.from_settings(load_settings())
    client.connect()
    point = mt5.symbol_info(SYMBOL).point
    offset = client._offset()  # noqa: SLF001 - server time = UTC + offset (lab script)
    since = datetime.now(UTC) - timedelta(days=30 * MONTHS)
    bars = [b for b in client.closed_bars(SYMBOL, Timeframe.H4, 2_000) if b.time >= since]
    spreads: list[int] = []
    by_hour: dict[int, list[int]] = {}
    missing = 0
    for bar in bars:
        close = bar.time + timedelta(hours=4)
        start = (close + offset).replace(tzinfo=None)
        ticks = mt5.copy_ticks_range(SYMBOL, start, start + WINDOW, mt5.COPY_TICKS_INFO)
        if ticks is None or len(ticks) == 0:
            missing += 1
            continue
        pts = round((float(ticks[0]["ask"]) - float(ticks[0]["bid"])) / point)
        spreads.append(pts)
        by_hour.setdefault(close.hour, []).append(pts)
    client.shutdown()
    if not spreads:
        print("no ticks found", file=sys.stderr)
        return 1
    qs = statistics.quantiles(spreads, n=20)
    result = {
        "symbol": SYMBOL, "closes": len(bars), "with_tick": len(spreads), "no_tick": missing,
        "median_points": statistics.median(spreads), "p75": qs[14], "p95": qs[18],
        "max": max(spreads), "model_points": MODEL_POINTS,
        "share_above_model": round(sum(s > MODEL_POINTS for s in spreads) / len(spreads), 3),
        "median_by_close_hour_utc": {h: statistics.median(v) for h, v in sorted(by_hour.items())},
        "b4_prime": "pass" if statistics.median(spreads) <= MODEL_POINTS else "rerun_gate_a",
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
