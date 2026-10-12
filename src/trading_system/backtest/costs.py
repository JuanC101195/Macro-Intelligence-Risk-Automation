"""Trading cost model for backtests (CLAUDE.md §12, ADR 0002 rule 4).

MetaQuotes-Demo spreads are unrealistic (EURUSD 0 in half of the bars, see
docs/progress.md), so the historical spread column is NOT used: each symbol gets a
fixed, conservative retail spread. `multiplier` scales every cost for the
sensitivity checks of ADR 0002 (x1.5, x2).

Defaults (points; 1 pip = 10 points on 5/3-digit quotes), chosen as typical retail
conditions WITHOUT looking at any backtest result:
  EURUSD 12 (1.2 pips), GBPUSD 16 (1.6 pips), USDJPY 14 (1.4 pips)
  slippage 2 points per fill (entry and stop exits; take-profit limits fill at price)
  commission 0 (spread-only account); swap not modelled (positions last hours).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_SPREADS: dict[str, int] = {
    "EURUSD": 12, "GBPUSD": 16, "USDJPY": 14,
    # Added with ADR 0004 (fixed before running the carry tests).
    "AUDUSD": 14, "NZDUSD": 18, "USDCAD": 18, "USDCHF": 16,
    # Added with ADR 0006 (fixed before running the breakout tests).
    "XAUUSD": 30, "XAGUSD": 30, "US500": 50, "US30": 200, "USTEC": 150,
}
# Slippage per fill in points where the FX default (2) would be unrealistically small.
DEFAULT_SLIPPAGE: dict[str, float] = {
    "XAUUSD": 5, "XAGUSD": 5, "US500": 20, "US30": 100, "USTEC": 50,
}


class CostModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    spread_points: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_SPREADS))
    slippage_points: float = 2.0  # default for instruments not in slippage_by_symbol
    slippage_by_symbol: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_SLIPPAGE))
    commission_per_lot_round_trip: float = 0.0  # account currency
    multiplier: float = Field(default=1.0, gt=0)

    def spread(self, symbol: str) -> float:
        if symbol not in self.spread_points:
            raise KeyError(f"no spread configured for {symbol}")
        return self.spread_points[symbol] * self.multiplier

    def slippage(self, symbol: str | None = None) -> float:
        base = self.slippage_by_symbol.get(symbol, self.slippage_points) if symbol else (
            self.slippage_points)
        return base * self.multiplier

    def commission(self, volume: float) -> float:
        return self.commission_per_lot_round_trip * volume * self.multiplier

    def scaled(self, multiplier: float) -> CostModel:
        return self.model_copy(update={"multiplier": multiplier})
