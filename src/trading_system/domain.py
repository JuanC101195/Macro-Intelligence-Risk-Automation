"""Enums shared by every package. See docs/architecture.md §5.1."""

from enum import StrEnum


class TradingMode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    DEMO = "demo"
    # Exists only so configuration can reject it explicitly. Blocked for the whole MVP.
    LIVE = "live"


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"


TIMEFRAME_MINUTES: dict[Timeframe, int] = {
    Timeframe.M1: 1,
    Timeframe.M5: 5,
    Timeframe.M15: 15,
    Timeframe.H1: 60,
    Timeframe.H4: 240,
    Timeframe.D1: 1440,
}


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


def bracket_error(is_long: bool, entry: float, stop_loss: float, take_profit: float) -> str | None:
    """Return why an entry/SL/TP bracket is invalid, or None if it is valid.

    LONG needs SL < entry < TP; SHORT needs TP < entry < SL. A stop on the wrong
    side of the entry would not limit the loss, so it is always rejected.
    """
    if min(entry, stop_loss, take_profit) <= 0:
        return "prices must be positive"
    if is_long and not (stop_loss < entry < take_profit):
        return "LONG requires stop_loss < entry < take_profit"
    if not is_long and not (take_profit < entry < stop_loss):
        return "SHORT requires take_profit < entry < stop_loss"
    return None
