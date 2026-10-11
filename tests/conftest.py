from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from trading_system.config import Settings, load_settings


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Tests never read the developer's real environment or .env file."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def _make(**overrides: Any) -> Settings:
        return load_settings(_env_file=None, **overrides)

    return _make
