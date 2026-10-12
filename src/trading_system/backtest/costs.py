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

DEFAULT_SPREADS: dict[str, int] = {"EURUSD": 12, "GBPUSD": 16, "USDJPY": 14}


class CostModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    spread_points: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_SPREADS))
    slippage_points: float = 2.0
    commission_per_lot_round_trip: float = 0.0  # account currency
    multiplier: float = Field(default=1.0, gt=0)

    def spread(self, symbol: str) -> float:
        if symbol not in self.spread_points:
            raise KeyError(f"no spread configured for {symbol}")
        return self.spread_points[symbol] * self.multiplier

    def slippage(self) -> float:
        return self.slippage_points * self.multiplier

    def commission(self, volume: float) -> float:
        return self.commission_per_lot_round_trip * volume * self.multiplier

    def scaled(self, multiplier: float) -> CostModel:
        return self.model_copy(update={"multiplier": multiplier})
