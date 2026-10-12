"""Crucix adapter: GET /api/data and /api/health only (CLAUDE.md §7).

Field mapping, verified against the Crucix source (server.mjs, dashboard/inject.mjs,
apis/sources/fred.mjs) at commit 3db7068, 2026-05-19:

| MacroContext     | Crucix /api/data                                         |
|------------------|----------------------------------------------------------|
| timestamp        | meta.timestamp (end of the last sweep)                   |
| vix              | markets.vix.value, else fred[VIXCLS].value               |
| vix_change_pct   | markets.vix.changePct                                    |
| yield_curve      | fred[T10Y2Y].value  (10Y-2Y, percentage points)          |
| credit_spread    | fred[BAMLH0A0HYM2].value  (HY OAS, percent)              |
| oil_change_pct   | markets.commodities[CL=F].changePct                      |
| gold_change_pct  | metals.goldChangePct                                     |
| urgent_events    | len(tg.urgent)                                           |
| conflict_events  | acled.totalEvents                                        |
| source_health    | meta.sourcesOk / meta.sourcesQueried                     |

Any malformed or missing piece degrades to None; a broken payload degrades to
MacroContext.unknown. `current()` never raises.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from trading_system.macro import regime_classifier
from trading_system.macro.macro_context import MacroContext
from trading_system.monitoring.logging import get_logger

log = get_logger(__name__)

_MAX_BODY_BYTES = 20 * 1024 * 1024


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _get(data: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(data, Mapping):
            return None
        data = data.get(key)
    return data


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _fred(data: Mapping[str, Any], series_id: str) -> float | None:
    for item in _list(data.get("fred")):
        if isinstance(item, Mapping) and item.get("id") == series_id:
            return _num(item.get("value"))
    return None


def _commodity_change(data: Mapping[str, Any], symbol: str) -> float | None:
    for item in _list(_get(data, "markets", "commodities")):
        if isinstance(item, Mapping) and item.get("symbol") == symbol:
            return _num(item.get("changePct"))
    return None


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else None


def normalize(data: Any, now: datetime, max_age: timedelta) -> MacroContext:
    """Turn a raw /api/data payload into a MacroContext. Pure function, never raises."""
    if not isinstance(data, Mapping):
        return MacroContext.unknown(now)
    ts = _parse_ts(_get(data, "meta", "timestamp"))
    if ts is None or ts > now + timedelta(minutes=5):  # missing or from the future
        return MacroContext.unknown(now)

    ok = _num(_get(data, "meta", "sourcesOk")) or 0.0
    queried = _num(_get(data, "meta", "sourcesQueried")) or 0.0
    source_health = max(0.0, min(1.0, ok / queried)) if queried > 0 else 0.0

    vix = _num(_get(data, "markets", "vix", "value"))
    if vix is None:
        vix = _fred(data, "VIXCLS")

    inputs = regime_classifier.MacroInputs(
        vix=vix,
        vix_change_pct=_num(_get(data, "markets", "vix", "changePct")),
        yield_curve=_fred(data, "T10Y2Y"),
        credit_spread=_fred(data, "BAMLH0A0HYM2"),
        gold_change_pct=_num(_get(data, "metals", "goldChangePct")),
        source_health=source_health,
        data_stale=now - ts > max_age,
    )
    regime, confidence, _reasons = regime_classifier.classify(inputs)
    urgent = _list(_get(data, "tg", "urgent"))
    conflicts = _num(_get(data, "acled", "totalEvents"))

    return MacroContext(
        timestamp=ts,
        risk_regime=regime,
        confidence=confidence,
        vix=inputs.vix,
        vix_change_pct=inputs.vix_change_pct,
        yield_curve=inputs.yield_curve,
        oil_change_pct=_commodity_change(data, "CL=F"),
        gold_change_pct=inputs.gold_change_pct,
        credit_spread=inputs.credit_spread,
        urgent_events=len(urgent),
        conflict_events=max(0, int(conflicts)) if conflicts is not None else 0,
        source_health=source_health,
        data_stale=inputs.data_stale,
    )


def raw_subset(data: Any) -> dict[str, Any]:
    """The parts of a payload worth archiving, so features can be re-derived later."""
    if not isinstance(data, Mapping):
        return {}
    keys = ("meta", "markets", "metals", "fred", "energy", "acled")
    subset = {k: data.get(k) for k in keys if k in data}
    subset["tg_urgent_count"] = len(_list(_get(data, "tg", "urgent")))
    gdelt = data.get("gdelt")
    if isinstance(gdelt, Mapping):
        subset["gdelt_counts"] = {
            k: gdelt.get(k) for k in ("totalArticles", "conflicts", "economy", "crisis")
        }
    return subset


class CrucixClient:
    """MacroProvider backed by a Crucix instance. Caches the last good payload."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 5.0,
        retries: int = 2,
        max_age: timedelta = timedelta(minutes=30),
        cache_ttl: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            transport=transport,
            follow_redirects=False,
        )
        self._retries = retries
        self._max_age = max_age
        self._cache_ttl = cache_ttl
        self._now = clock or (lambda: datetime.now(UTC))
        self._cached: tuple[datetime, Any] | None = None  # (fetched_at, payload)

    def close(self) -> None:
        self._http.close()

    def healthy(self) -> bool:
        body = self._get_json("/api/health")
        return isinstance(body, Mapping) and body.get("status") == "ok"

    def current(self) -> MacroContext:
        payload = self.fetch_raw()
        now = self._now()
        if payload is None:
            return MacroContext.unknown(now)
        try:
            return normalize(payload, now, self._max_age)
        except Exception as exc:  # noqa: BLE001 - contract: never raise
            log.warning("crucix_normalize_failed", error=type(exc).__name__)
            return MacroContext.unknown(now)

    def fetch_raw(self) -> Any | None:
        """Last good /api/data payload (cached for cache_ttl). None if unavailable."""
        now = self._now()
        if self._cached and now - self._cached[0] < self._cache_ttl:
            return self._cached[1]
        payload = self._get_json("/api/data")
        if payload is not None:
            self._cached = (now, payload)
            return payload
        # Serve the old payload: normalize() will flag it stale by its own timestamp.
        return self._cached[1] if self._cached else None

    def _get_json(self, path: str) -> Any | None:
        for attempt in range(self._retries + 1):
            try:
                resp = self._http.get(path)
                if resp.status_code == 200 and len(resp.content) <= _MAX_BODY_BYTES:
                    return resp.json()
                log.warning("crucix_bad_response", path=path, status=resp.status_code,
                            attempt=attempt)
                if resp.status_code < 500:
                    return None  # client errors will not fix themselves
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("crucix_request_failed", path=path, error=type(exc).__name__,
                            attempt=attempt)
        return None
