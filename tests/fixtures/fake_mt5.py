"""In-memory stand-in for the `MetaTrader5` module.

Mimics the parts of the real API the client uses, including the two traps that
matter: timestamps are server-local epochs (not UTC), and position 0 of
`copy_rates_from_pos` is the bar that is still forming. It has no order_send.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

TIMEFRAME_MINUTES = {1: 1, 5: 5, 15: 15, 16385: 60, 16388: 240, 16408: 1440}

SPECS: dict[str, dict[str, Any]] = {
    "EURUSD": {"digits": 5, "point": 1e-5, "tick_value": 1.0, "base": "EUR", "profit": "USD",
               "price": 1.0825},
    "GBPUSD": {"digits": 5, "point": 1e-5, "tick_value": 1.0, "base": "GBP", "profit": "USD",
               "price": 1.2710},
    "USDJPY": {"digits": 3, "point": 1e-3, "tick_value": 100 / 150.0, "base": "USD",
               "profit": "JPY", "price": 150.000},
}


def floor_to(dt: datetime, minutes: int) -> datetime:
    epoch = int(dt.timestamp())
    return datetime.fromtimestamp(epoch - epoch % (minutes * 60), tz=UTC)


@dataclass
class FakeMt5:
    now: datetime
    server_offset: timedelta = timedelta(hours=3)
    trade_mode: int = 0  # 0 demo, 1 contest, 2 real
    login: int = 51234567
    tick_age: timedelta = timedelta(seconds=2)
    bars_per_symbol: int = 300
    fail: set[str] = field(default_factory=set)
    positions: list[SimpleNamespace] = field(default_factory=list)
    init_kwargs: dict[str, Any] | None = None
    connected: bool = True

    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385
    TIMEFRAME_H4 = 16388
    TIMEFRAME_D1 = 16408

    def __post_init__(self) -> None:
        self._rates = {s: self._make_rates(s) for s in SPECS}

    # --- helpers ---------------------------------------------------------------

    def server_epoch(self, utc: datetime) -> int:
        return int((utc + self.server_offset).timestamp())

    def _make_rates(self, symbol: str) -> list[dict[str, Any]]:
        """M15 bars; the last one is the forming bar containing `now`."""
        spec = SPECS[symbol]
        last_open = floor_to(self.now, 15)
        rows = []
        for i in range(self.bars_per_symbol):
            open_utc = last_open - timedelta(minutes=15 * (self.bars_per_symbol - 1 - i))
            mid = spec["price"] * (1 + 0.002 * math.sin(i / 7))
            step = spec["point"] * 50
            rows.append({
                "time": self.server_epoch(open_utc),
                "open": round(mid, spec["digits"]),
                "high": round(mid + step, spec["digits"]),
                "low": round(mid - step, spec["digits"]),
                "close": round(mid + step / 2, spec["digits"]),
                "tick_volume": 100 + i,
                "spread": 12,
                "real_volume": 0,
            })
        return rows

    def _maybe_fail(self, name: str) -> bool:
        return name in self.fail

    # --- MetaTrader5 API -------------------------------------------------------

    def initialize(self, **kwargs: Any) -> bool:
        self.init_kwargs = kwargs
        return not self._maybe_fail("initialize")

    def shutdown(self) -> None:
        self.connected = False

    def last_error(self) -> tuple[int, str]:
        return (-10005, "IPC timeout")

    def terminal_info(self) -> SimpleNamespace | None:
        return None if self._maybe_fail("terminal_info") else SimpleNamespace(
            connected=self.connected
        )

    def account_info(self) -> SimpleNamespace | None:
        if self._maybe_fail("account_info"):
            return None
        return SimpleNamespace(
            login=self.login, server="MetaQuotes-Demo", trade_mode=self.trade_mode,
            currency="USD", balance=10_000.0, equity=10_000.0, margin=0.0,
            margin_free=10_000.0, leverage=100,
        )

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        return symbol in SPECS and not self._maybe_fail("symbol_select")

    def symbol_info(self, symbol: str) -> SimpleNamespace | None:
        if symbol not in SPECS or self._maybe_fail("symbol_info"):
            return None
        s = SPECS[symbol]
        return SimpleNamespace(
            name=symbol, digits=s["digits"], point=s["point"], trade_tick_size=s["point"],
            trade_tick_value=s["tick_value"], trade_contract_size=100_000.0,
            volume_min=0.01, volume_max=100.0, volume_step=0.01,
            trade_stops_level=0, trade_freeze_level=0,
            currency_base=s["base"], currency_profit=s["profit"], currency_margin=s["base"],
            trade_mode=4,
        )

    def symbol_info_tick(self, symbol: str) -> SimpleNamespace | None:
        if symbol not in SPECS or self._maybe_fail("symbol_info_tick"):
            return None
        s = SPECS[symbol]
        bid = s["price"]
        return SimpleNamespace(
            time=self.server_epoch(self.now - self.tick_age),
            bid=bid, ask=round(bid + 12 * s["point"], s["digits"]),
        )

    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> list[dict[str, Any]] | None:
        if self._maybe_fail("copy_rates_from_pos") or timeframe != 15:
            return None
        rates = self._rates[symbol]
        end = len(rates) - start_pos
        return rates[max(0, end - count):end]

    def copy_rates_range(
        self, symbol: str, timeframe: int, date_from: datetime, date_to: datetime
    ) -> list[dict[str, Any]] | None:
        if self._maybe_fail("copy_rates_range") or timeframe != 15:
            return None
        # Naive datetimes are interpreted as server time, like the real terminal.
        lo = int(date_from.replace(tzinfo=UTC).timestamp())
        hi = int(date_to.replace(tzinfo=UTC).timestamp())
        return [r for r in self._rates[symbol] if lo <= r["time"] <= hi]

    def positions_get(self, symbol: str | None = None) -> tuple[SimpleNamespace, ...] | None:
        if self._maybe_fail("positions_get"):
            return None
        return tuple(p for p in self.positions if symbol is None or p.symbol == symbol)

    def order_calc_margin(
        self, action: int, symbol: str, volume: float, price: float
    ) -> float | None:
        if self._maybe_fail("order_calc_margin"):
            return None
        return volume * 100_000 * price / 100  # 1:100 leverage, USD account

    def order_calc_profit(
        self, action: int, symbol: str, volume: float, price_open: float, price_close: float
    ) -> float | None:
        if self._maybe_fail("order_calc_profit"):
            return None
        sign = 1 if action == 0 else -1
        raw = sign * (price_close - price_open) * volume * 100_000
        return raw / price_close if SPECS[symbol]["profit"] == "JPY" else raw
