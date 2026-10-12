"""Historical bar download to Parquet, with a manifest carrying the data hash.

The hash makes backtests reproducible: a backtest records the exact dataset it used
(docs/architecture.md §5.8, `BacktestConfig.data_hash`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import pyarrow as pa
import pyarrow.parquet as pq

from trading_system.broker.contracts import Bar
from trading_system.domain import Timeframe

SCHEMA = pa.schema(
    [
        ("time", pa.timestamp("s", tz="UTC")),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("tick_volume", pa.int64()),
        ("spread_points", pa.int64()),
        ("real_volume", pa.int64()),
    ]
)


class HistoricalBarsSource(Protocol):
    def bars_range(
        self, symbol: str, tf: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]: ...


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bars(bars: Sequence[Bar], path: Path) -> str:
    """Write bars to Parquet and return the file's sha256."""
    times = [b.time for b in bars]
    if times != sorted(times) or len(set(times)) != len(times):
        raise ValueError("bars must be strictly increasing in time")
    table = pa.Table.from_pylist([b.model_dump() for b in bars], schema=SCHEMA)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return file_sha256(path)


def read_bars(path: Path) -> list[Bar]:
    return [Bar(**row) for row in pq.read_table(path, schema=SCHEMA).to_pylist()]


def download(
    source: HistoricalBarsSource,
    symbol: str,
    tf: Timeframe,
    start: datetime,
    end: datetime,
    out_dir: Path,
) -> Path:
    """Download [start, end) and write `<SYMBOL>_<TF>_<start>_<end>.parquet` plus a manifest."""
    bars = source.bars_range(symbol, tf, start, end)
    if not bars:
        raise ValueError(f"no bars returned for {symbol} {tf} {start:%Y-%m-%d}..{end:%Y-%m-%d}")
    stem = f"{symbol}_{tf.value}_{start:%Y%m%d}_{end:%Y%m%d}"
    path = out_dir / f"{stem}.parquet"
    sha = write_bars(bars, path)
    manifest = {
        "symbol": symbol,
        "timeframe": tf.value,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "bars": len(bars),
        "first_bar": bars[0].time.isoformat(),
        "last_bar": bars[-1].time.isoformat(),
        "sha256": sha,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "source": "mt5",
    }
    (out_dir / f"{stem}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path
