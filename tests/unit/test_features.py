from __future__ import annotations

from tests.fixtures.bars import random_walk
from trading_system.strategy.features import FEATURE_NAMES, feature_rows


def test_feature_names_and_warmup() -> None:
    rows = feature_rows(random_walk(400))
    first = next(i for i, r in enumerate(rows) if r is not None)
    assert first == 199  # EMA200 is the slowest indicator
    row = rows[-1]
    assert row is not None
    assert tuple(row) == FEATURE_NAMES
    assert 0 <= row["rsi"] <= 100
    assert row["atr_percent"] > 0
    assert 0 <= row["hour"] <= 23


def test_features_have_no_look_ahead() -> None:
    bars = random_walk(400, seed=3)
    full = feature_rows(bars)
    for k in (250, 320):
        assert feature_rows(bars[:k]) == full[:k]
