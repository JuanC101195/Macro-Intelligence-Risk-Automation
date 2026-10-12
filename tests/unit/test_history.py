from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fixtures.fake_mt5 import FakeMt5
from trading_system.broker import history
from trading_system.broker.mt5_client import Mt5Client
from trading_system.domain import Timeframe

NOW = datetime(2026, 10, 14, 13, 37, 12, tzinfo=UTC)


def _client() -> Mt5Client:
    fake = FakeMt5(now=NOW, bars_per_symbol=500)
    return Mt5Client(fake, clock=lambda: NOW, utc_offset_minutes=180)


def test_download_roundtrip_with_manifest(tmp_path: Path) -> None:
    start = datetime(2026, 10, 12, tzinfo=UTC)
    end = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
    path = history.download(_client(), "EURUSD", Timeframe.M15, start, end, tmp_path)

    bars = history.read_bars(path)
    assert bars[0].time >= start
    assert bars[-1].time < end
    assert all(b.time + timedelta(minutes=15) <= NOW for b in bars)

    manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert manifest["bars"] == len(bars)
    assert manifest["sha256"] == history.file_sha256(path)


def test_same_data_same_hash(tmp_path: Path) -> None:
    start = datetime(2026, 10, 13, tzinfo=UTC)
    end = datetime(2026, 10, 14, tzinfo=UTC)
    bars = _client().bars_range("GBPUSD", Timeframe.M15, start, end)
    assert history.write_bars(bars, tmp_path / "a.parquet") == history.write_bars(
        bars, tmp_path / "b.parquet"
    )


def test_unsorted_bars_rejected(tmp_path: Path) -> None:
    bars = _client().bars_range(
        "EURUSD", Timeframe.M15, datetime(2026, 10, 13, tzinfo=UTC),
        datetime(2026, 10, 14, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="increasing"):
        history.write_bars(list(reversed(bars)), tmp_path / "x.parquet")


def test_empty_range_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no bars"):
        history.download(
            _client(), "EURUSD", Timeframe.M15, datetime(2020, 1, 1, tzinfo=UTC),
            datetime(2020, 1, 2, tzinfo=UTC), tmp_path,
        )


def test_naive_range_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        _client().bars_range(
            "EURUSD", Timeframe.M15, datetime(2026, 10, 13), datetime(2026, 10, 14)  # noqa: DTZ001
        )
