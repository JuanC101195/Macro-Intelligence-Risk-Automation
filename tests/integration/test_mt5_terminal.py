"""Talks to the real MT5 terminal with the credentials in the repo's .env.

Excluded by default. Run manually with:  pytest -m mt5
Read-only: never sends orders. Refuses to pass against a non-demo account.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_system.broker.mt5_client import Mt5Client
from trading_system.config import load_settings
from trading_system.domain import Timeframe

REPO_ENV = Path(__file__).resolve().parents[2] / ".env"

pytestmark = pytest.mark.mt5


@pytest.fixture(scope="module")
def client() -> Mt5Client:
    if not REPO_ENV.exists():
        pytest.skip("no .env with MT5 credentials")
    settings = load_settings(_env_file=REPO_ENV)
    c = Mt5Client.from_settings(settings)
    c.connect()
    return c


def test_account_is_demo(client: Mt5Client) -> None:
    assert client.account_info().trade_mode == "demo"


@pytest.mark.parametrize("symbol", ["EURUSD", "GBPUSD", "USDJPY"])
def test_symbols_and_bars(client: Mt5Client, symbol: str) -> None:
    spec = client.symbol_spec(symbol)
    assert spec.volume_min > 0
    bars = client.closed_bars(symbol, Timeframe.M15, 50)
    assert len(bars) == 50
