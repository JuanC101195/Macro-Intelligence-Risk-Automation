"""Read-only MetaTrader 5 client. The ONLY module that imports `MetaTrader5`.

Key behaviours (docs/architecture.md §5.2, docs/implementation-plan.md Phase 2):
- Converts MT5 server timestamps to real UTC (MT5 epochs are server-local time).
  The server offset must be configured; fresh ticks are only used to cross-check
  it, so a broker DST switch stops the client instead of shifting every timestamp.
- `closed_bars` never returns the candle that is still forming.
- The full account login never leaves this module (`login_masked`).
- No order-sending capability: that arrives in Phase 11 behind `OrderGateway`.

The MetaTrader5 module is injected so the client can be tested with a fake.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import SecretStr

from trading_system.broker.contracts import AccountInfo, Bar, Position, SymbolSpec, Tick
from trading_system.config import Settings
from trading_system.domain import Timeframe

TIMEFRAME_MINUTES: dict[Timeframe, int] = {
    Timeframe.M1: 1,
    Timeframe.M5: 5,
    Timeframe.M15: 15,
    Timeframe.H1: 60,
    Timeframe.H4: 240,
    Timeframe.D1: 1440,
}

# MT5 constants, duplicated so behaviour does not depend on the fake defining them.
_ACCOUNT_TRADE_MODE: dict[int, Literal["demo", "contest", "real"]] = {
    0: "demo",
    1: "contest",
    2: "real",
}
_SYMBOL_TRADE_MODE_LONGONLY = 1
_SYMBOL_TRADE_MODE_SHORTONLY = 2
_SYMBOL_TRADE_MODE_FULL = 4
_ORDER_TYPE = {"buy": 0, "sell": 1}

# A tick younger than this can be used to infer the server's UTC offset.
_FRESH_TICK = timedelta(minutes=5)
# Offsets are whole half-hours; anything further off means the tick is not fresh.
_OFFSET_TOLERANCE = timedelta(minutes=5)


class BrokerError(Exception):
    """Broker call failed. Message never contains credentials."""


def mask_login(login: str) -> str:
    return "****" + login[-4:] if len(login) > 4 else "****"


_MIN_OFFSET = timedelta(hours=-12)
_MAX_OFFSET = timedelta(hours=14)


def fx_market_open(now_utc: datetime) -> bool:
    """Conservative FX weekly session: Sunday 22:00 UTC to Friday 21:00 UTC."""
    weekday, hour = now_utc.weekday(), now_utc.hour  # Monday = 0
    if weekday == 5:  # Saturday
        return False
    if weekday == 6:  # Sunday
        return hour >= 22
    if weekday == 4:  # Friday
        return hour < 21
    return True


def infer_utc_offset(server_epoch: int, now_utc: datetime) -> timedelta | None:
    """Best-effort server UTC offset from a tick, rounded to 30 minutes.

    NOT reliable on its own: a stale tick whose age is close to a multiple of
    30 minutes looks fresh. It is used only as a cross-check of the configured
    offset and as a suggestion, never as the source of truth.
    """
    server_as_utc = datetime.fromtimestamp(server_epoch, tz=UTC)
    raw = server_as_utc - now_utc
    rounded = timedelta(minutes=30 * round(raw.total_seconds() / 1800))
    lag = rounded - raw  # how old the tick is, once the offset is removed
    if not (_MIN_OFFSET <= rounded <= _MAX_OFFSET):
        return None
    if timedelta(0) - _OFFSET_TOLERANCE <= lag <= _FRESH_TICK:
        return rounded
    return None


class Mt5Client:
    def __init__(
        self,
        mt5_module: Any | None = None,
        *,
        login: str | None = None,
        password: str | None = None,
        server: str | None = None,
        path: str | None = None,
        timeout_ms: int = 10_000,
        utc_offset_minutes: int | None = None,
        clock: Any = None,
    ) -> None:
        if mt5_module is None:
            import MetaTrader5 as mt5_module  # type: ignore[import-untyped,import-not-found,no-redef,unused-ignore]  # noqa: N813
        self._mt5: Any = mt5_module
        self._login = login
        self._password = password
        self._server = server
        self._path = path
        self._timeout_ms = timeout_ms
        self._fixed_offset = (
            timedelta(minutes=utc_offset_minutes) if utc_offset_minutes is not None else None
        )
        self._observed_offset: timedelta | None = None
        self._now = clock or (lambda: datetime.now(UTC))

    @classmethod
    def from_settings(cls, settings: Settings, mt5_module: Any | None = None) -> Mt5Client:
        def secret(value: SecretStr | None) -> str | None:
            return value.get_secret_value() if value is not None else None

        return cls(
            mt5_module,
            login=secret(settings.mt5_login),
            password=secret(settings.mt5_password),
            server=settings.mt5_server,
            path=settings.mt5_path,
            timeout_ms=settings.mt5_timeout_ms,
            utc_offset_minutes=settings.mt5_server_utc_offset_minutes,
        )

    # --- connection -------------------------------------------------------------

    def connect(self) -> None:
        kwargs: dict[str, Any] = {"timeout": self._timeout_ms}
        if self._path:
            kwargs["path"] = self._path
        if self._login:
            if not self._login.isdigit():
                raise BrokerError("MT5_LOGIN must be numeric")
            kwargs["login"] = int(self._login)
        if self._password:
            kwargs["password"] = self._password
        if self._server:
            kwargs["server"] = self._server
        if not self._mt5.initialize(**kwargs):
            raise BrokerError(f"MT5 initialize failed: {self._last_error()}")

    def shutdown(self) -> None:
        self._mt5.shutdown()

    def is_connected(self) -> bool:
        info = self._mt5.terminal_info()
        return bool(info is not None and getattr(info, "connected", False))

    # --- account and symbols --------------------------------------------------

    def account_info(self) -> AccountInfo:
        info = self._call("account_info")
        mode = _ACCOUNT_TRADE_MODE.get(info.trade_mode)
        if mode is None:
            raise BrokerError(f"unknown account trade_mode {info.trade_mode}")
        return AccountInfo(
            login_masked=mask_login(str(info.login)),
            server=info.server,
            trade_mode=mode,
            currency=info.currency,
            balance=info.balance,
            equity=info.equity,
            margin=info.margin,
            margin_free=info.margin_free,
            leverage=info.leverage,
        )

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        if not self._mt5.symbol_select(symbol, True):
            raise BrokerError(f"symbol {symbol} not available: {self._last_error()}")
        s = self._call("symbol_info", symbol)
        return SymbolSpec(
            symbol=s.name,
            digits=s.digits,
            point=s.point,
            tick_size=s.trade_tick_size,
            tick_value=s.trade_tick_value,
            contract_size=s.trade_contract_size,
            volume_min=s.volume_min,
            volume_max=s.volume_max,
            volume_step=s.volume_step,
            stops_level_points=s.trade_stops_level,
            freeze_level_points=s.trade_freeze_level,
            currency_base=s.currency_base,
            currency_profit=s.currency_profit,
            currency_margin=s.currency_margin,
            trade_allowed=s.trade_mode
            in (_SYMBOL_TRADE_MODE_LONGONLY, _SYMBOL_TRADE_MODE_SHORTONLY, _SYMBOL_TRADE_MODE_FULL),
            short_allowed=s.trade_mode in (_SYMBOL_TRADE_MODE_SHORTONLY, _SYMBOL_TRADE_MODE_FULL),
        )

    # --- market data ------------------------------------------------------------

    def last_tick(self, symbol: str) -> Tick:
        t = self._call("symbol_info_tick", symbol)
        self._observe_tick(t.time)
        spec = self._call("symbol_info", symbol)
        return Tick(
            time=self._to_utc(t.time),
            bid=t.bid,
            ask=t.ask,
            spread_points=round((t.ask - t.bid) / spec.point),
        )

    def closed_bars(self, symbol: str, tf: Timeframe, count: int) -> list[Bar]:
        """Last `count` CLOSED bars, oldest first. The forming bar is always dropped."""
        if count < 1:
            raise ValueError("count must be >= 1")
        self._refresh_offset(symbol)
        rates = self._mt5.copy_rates_from_pos(symbol, self._tf(tf), 0, count + 1)
        if rates is None:
            raise BrokerError(f"copy_rates_from_pos failed: {self._last_error()}")
        bars = [self._bar(r) for r in rates]
        now = self._now()
        duration = timedelta(minutes=TIMEFRAME_MINUTES[tf])
        closed = [b for b in bars if b.time + duration <= now]
        return closed[-count:]

    def bars_range(
        self, symbol: str, tf: Timeframe, start: datetime, end: datetime
    ) -> list[Bar]:
        """Closed bars whose open time is in [start, end), both UTC. For history downloads."""
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        offset = self._offset()
        # MT5 interprets the datetimes as server time.
        rates = self._mt5.copy_rates_range(
            symbol, self._tf(tf), (start + offset).replace(tzinfo=None),
            (end + offset).replace(tzinfo=None),
        )
        if rates is None:
            raise BrokerError(f"copy_rates_range failed: {self._last_error()}")
        duration = timedelta(minutes=TIMEFRAME_MINUTES[tf])
        now = self._now()
        bars = [self._bar(r) for r in rates]
        return [b for b in bars if start <= b.time < end and b.time + duration <= now]

    def positions(self, symbol: str | None = None) -> list[Position]:
        raw = self._mt5.positions_get(symbol=symbol) if symbol else self._mt5.positions_get()
        if raw is None:
            raise BrokerError(f"positions_get failed: {self._last_error()}")
        return [
            Position(
                ticket=p.ticket,
                symbol=p.symbol,
                side="buy" if p.type == 0 else "sell",
                volume=p.volume,
                open_price=p.price_open,
                stop_loss=p.sl or None,  # MT5 uses 0.0 for "no stop"
                take_profit=p.tp or None,
                open_time=self._to_utc(p.time),
                profit=p.profit,
                magic=p.magic,
                comment=p.comment,
            )
            for p in raw
        ]

    def calc_margin(
        self, symbol: str, side: Literal["buy", "sell"], volume: float, price: float
    ) -> float:
        value = self._mt5.order_calc_margin(_ORDER_TYPE[side], symbol, volume, price)
        if value is None:
            raise BrokerError(f"order_calc_margin failed: {self._last_error()}")
        return float(value)

    def calc_profit(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        volume: float,
        price_open: float,
        price_close: float,
    ) -> float:
        value = self._mt5.order_calc_profit(
            _ORDER_TYPE[side], symbol, volume, price_open, price_close
        )
        if value is None:
            raise BrokerError(f"order_calc_profit failed: {self._last_error()}")
        return float(value)

    # --- internals --------------------------------------------------------------

    def _call(self, name: str, *args: Any) -> Any:
        result = getattr(self._mt5, name)(*args)
        if result is None:
            raise BrokerError(f"{name} failed: {self._last_error()}")
        return result

    def _last_error(self) -> str:
        try:
            code, message = self._mt5.last_error()
        except Exception:  # noqa: BLE001 - diagnostics must never raise
            return "unknown error"
        return f"{code} {message}"

    def _tf(self, tf: Timeframe) -> int:
        return int(getattr(self._mt5, f"TIMEFRAME_{tf.value}"))

    def _bar(self, r: Any) -> Bar:
        real_volume = int(r["real_volume"])
        return Bar(
            time=self._to_utc(int(r["time"])),
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            tick_volume=int(r["tick_volume"]),
            spread_points=int(r["spread"]),
            real_volume=real_volume or None,
        )

    def probe_utc_offset_minutes(self, symbol: str) -> int | None:
        """Look at a fresh tick and return the observed offset (None if market closed).

        Raises BrokerError if it contradicts the configured offset.
        """
        self._refresh_offset(symbol)
        return self.observed_utc_offset_minutes()

    def observed_utc_offset_minutes(self) -> int | None:
        """Offset suggested by the last fresh tick, for diagnostics (`mt5 check`)."""
        if self._observed_offset is None:
            return None
        return int(self._observed_offset.total_seconds() // 60)

    def _observe_tick(self, server_epoch: int) -> None:
        now = self._now()
        if not fx_market_open(now):
            return
        observed = infer_utc_offset(server_epoch, now)
        if observed is None:
            return
        self._observed_offset = observed
        if self._fixed_offset is not None and observed != self._fixed_offset:
            # Typical cause: the broker switched daylight saving time.
            raise BrokerError(
                "MT5 server UTC offset mismatch: configured "
                f"{int(self._fixed_offset.total_seconds() // 60)} min, observed "
                f"{int(observed.total_seconds() // 60)} min. "
                "Check MT5_SERVER_UTC_OFFSET_MINUTES (DST change?)"
            )

    def _refresh_offset(self, symbol: str) -> None:
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is not None:
            self._observe_tick(tick.time)

    def _offset(self) -> timedelta:
        if self._fixed_offset is not None:
            return self._fixed_offset
        # Fail closed: wrong timestamps would silently corrupt every signal.
        hint = self.observed_utc_offset_minutes()
        suggestion = f" (observed: {hint})" if hint is not None else ""
        raise BrokerError(f"MT5_SERVER_UTC_OFFSET_MINUTES is not set{suggestion}")

    def _to_utc(self, server_epoch: int) -> datetime:
        return datetime.fromtimestamp(server_epoch, tz=UTC) - self._offset()
