"""Contract specifications per instrument for backtests (USD account).

Values copied from MetaQuotes-Demo `symbol_info` on 2026-10-12 (ADR 0006). Profit
is in USD for every instrument except USDXXX pairs, whose profit currency is the
quote and is converted at the pair's own price.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class InstrumentInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    digits: int
    point: float
    contract_size: float
    volume_min: float
    volume_step: float
    volume_max: float = 100.0
    base: str
    profit_currency: str
    leverage: int  # notional / margin
    asset_class: Literal["fx", "metal", "index"]


def _fx(symbol: str) -> InstrumentInfo:
    jpy = symbol.endswith("JPY")
    return InstrumentInfo(symbol=symbol, digits=3 if jpy else 5, point=1e-3 if jpy else 1e-5,
                          contract_size=100_000.0, volume_min=0.01, volume_step=0.01,
                          base=symbol[:3], profit_currency=symbol[3:], leverage=100,
                          asset_class="fx")


def _index(symbol: str) -> InstrumentInfo:
    return InstrumentInfo(symbol=symbol, digits=2, point=0.01, contract_size=1.0,
                          volume_min=0.1, volume_step=0.1, base=symbol,
                          profit_currency="USD", leverage=20, asset_class="index")


INSTRUMENTS: dict[str, InstrumentInfo] = {
    **{s: _fx(s) for s in ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCAD",
                           "USDCHF")},
    "XAUUSD": InstrumentInfo(symbol="XAUUSD", digits=2, point=0.01, contract_size=100.0,
                             volume_min=0.01, volume_step=0.01, base="XAU",
                             profit_currency="USD", leverage=50, asset_class="metal"),
    "XAGUSD": InstrumentInfo(symbol="XAGUSD", digits=3, point=0.001, contract_size=5_000.0,
                             volume_min=0.01, volume_step=0.01, base="XAG",
                             profit_currency="USD", leverage=50, asset_class="metal"),
    **{s: _index(s) for s in ("US500", "US30", "USTEC")},
}


def info(symbol: str) -> InstrumentInfo:
    if symbol in INSTRUMENTS:
        return INSTRUMENTS[symbol]
    if len(symbol) == 6 and "USD" in (symbol[:3], symbol[3:]):
        return _fx(symbol)
    raise ValueError(f"no contract specification for {symbol}")


def is_fx(symbol: str) -> bool:
    return info(symbol).asset_class == "fx"
