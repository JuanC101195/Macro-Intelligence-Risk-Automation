"""Short-term interest rates per currency from FRED (ADR 0004).

Series: OECD 3-month interbank rate, monthly, `IR3TIB01{CC}M156N` (percent).
No look-ahead: the value for month M (dated day 1 of M) is AVAILABLE from day 1 of
month M+2, 00:00 UTC, which is later than its real publication.
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime

from trading_system.macro.fred_history import Observation

FRED_COUNTRY: dict[str, str] = {
    "USD": "US", "EUR": "EZ", "GBP": "GB", "JPY": "JP",
    "AUD": "AU", "NZD": "NZ", "CAD": "CA", "CHF": "CH",
}


def series_id(currency: str) -> str:
    return f"IR3TIB01{FRED_COUNTRY[currency]}M156N"


def available_from(month: date) -> datetime:
    """First instant a monthly value may be used: day 1 of month M+2, 00:00 UTC."""
    index = month.year * 12 + month.month - 1 + 2
    return datetime(index // 12, index % 12 + 1, 1, tzinfo=UTC)


class RateHistory:
    """Point-in-time short rates: `rates.rate_at("AUD", t)` in percent, or None."""

    def __init__(self, series: Mapping[str, Sequence[Observation]]) -> None:
        self._values: dict[str, list[float]] = {}
        self._avail: dict[str, list[datetime]] = {}
        for ccy, obs in series.items():
            ordered = sorted(obs)
            self._values[ccy] = [v for _, v in ordered]
            self._avail[ccy] = [available_from(d) for d, _ in ordered]

    def rate_at(self, currency: str, t: datetime) -> float | None:
        avail = self._avail.get(currency)
        if not avail:
            return None
        i = bisect.bisect_right(avail, t) - 1
        return self._values[currency][i] if i >= 0 else None

    def differential(self, symbol: str, t: datetime) -> float | None:
        """rate(base) - rate(quote) in percentage points, e.g. AUDUSD -> AUD - USD."""
        base, quote = self.rate_at(symbol[:3], t), self.rate_at(symbol[3:], t)
        if base is None or quote is None:
            return None
        return base - quote
