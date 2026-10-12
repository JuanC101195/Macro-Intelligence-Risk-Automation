"""Historical macro context from FRED daily series (ADR 0003).

Crucix has no history, but the variables the regime classifier uses exist in FRED
for decades. This module rebuilds a point-in-time MacroContext for any instant:

- an observation dated D is only AVAILABLE from D+1 22:00 UTC (FRED publishes some
  series with a one-day delay; conservative so a backtest never sees the future);
- the classifier is regime-rules-v001, unchanged;
- gold has no free current daily FRED series, so it is None (the classifier allows it).
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import httpx

from trading_system.macro import regime_classifier
from trading_system.macro.macro_context import MacroContext

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
VIX, HY_SPREAD, CURVE = "VIXCLS", "BAMLH0A0HYM2", "T10Y2Y"
SERIES = (VIX, HY_SPREAD, CURVE)
AVAILABLE_AFTER = timedelta(days=1, hours=22)  # D 00:00 UTC + 1 day 22 h
MAX_AGE = timedelta(days=4)  # older than this -> stale (covers weekends and holidays)

Observation = tuple[date, float]


def available_at(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=UTC) + AVAILABLE_AFTER


def fetch_series(series_id: str, api_key: str, start: date,
                 client: httpx.Client | None = None) -> list[Observation]:
    """Daily observations from FRED; missing values ('.') are skipped."""
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json",
              "observation_start": start.isoformat()}
    own = client is None
    http = client or httpx.Client(timeout=30)
    try:
        resp = http.get(FRED_URL, params=params)
        if resp.status_code != 200:
            # Never echo the URL: it carries the API key.
            raise RuntimeError(f"FRED {series_id}: HTTP {resp.status_code}")
        rows = resp.json().get("observations", [])
    finally:
        if own:
            http.close()
    out: list[Observation] = []
    for row in rows:
        try:
            out.append((date.fromisoformat(row["date"]), float(row["value"])))
        except (KeyError, ValueError):
            continue  # "." = no observation that day
    return out


def save(series: Mapping[str, Sequence[Observation]], path: Path) -> None:
    payload = {sid: [[d.isoformat(), v] for d, v in obs] for sid, obs in series.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def load(path: Path) -> dict[str, list[Observation]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {sid: [(date.fromisoformat(d), float(v)) for d, v in obs] for sid, obs in raw.items()}


class FredMacroHistory:
    """Point-in-time MacroContext provider: `history.context_at(t)`."""

    def __init__(self, series: Mapping[str, Sequence[Observation]]) -> None:
        self._obs = {sid: sorted(series.get(sid, ())) for sid in SERIES}
        self._avail = {sid: [available_at(d) for d, _ in obs] for sid, obs in self._obs.items()}

    def _latest(self, sid: str, t: datetime) -> tuple[int, Observation] | None:
        i = bisect.bisect_right(self._avail[sid], t) - 1
        return (i, self._obs[sid][i]) if i >= 0 else None

    def context_at(self, t: datetime) -> MacroContext:
        vix = self._latest(VIX, t)
        if vix is None:
            return MacroContext.unknown(t)
        i, (vix_day, vix_value) = vix
        prev = self._obs[VIX][i - 1][1] if i > 0 else None
        hy, curve = self._latest(HY_SPREAD, t), self._latest(CURVE, t)
        present = sum(x is not None for x in (vix, hy, curve))
        stale = t - available_at(vix_day) > MAX_AGE
        inputs = regime_classifier.MacroInputs(
            vix=vix_value,
            vix_change_pct=(vix_value / prev - 1) * 100 if prev else None,
            yield_curve=curve[1][1] if curve else None,
            credit_spread=hy[1][1] if hy else None,
            gold_change_pct=None,
            source_health=present / len(SERIES),
            data_stale=stale,
        )
        regime, confidence, _ = regime_classifier.classify(inputs)
        return MacroContext(
            timestamp=available_at(vix_day), risk_regime=regime, confidence=confidence,
            vix=inputs.vix, vix_change_pct=inputs.vix_change_pct,
            yield_curve=inputs.yield_curve, credit_spread=inputs.credit_spread,
            source_health=inputs.source_health, data_stale=stale,
        )
