from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest

from trading_system.macro import fred_history as fh

# Mon 2024-03-04 .. Fri 2024-03-08
CALM = {
    fh.VIX: [(date(2024, 3, 4), 14.0), (date(2024, 3, 5), 13.0), (date(2024, 3, 8), 13.5)],
    fh.HY_SPREAD: [(date(2024, 3, 4), 3.2), (date(2024, 3, 5), 3.1)],
    fh.CURVE: [(date(2024, 3, 4), 0.3)],
}


def test_value_is_only_visible_after_publication_lag() -> None:
    h = fh.FredMacroHistory(CALM)
    # Tuesday 21:59 UTC: Monday's value is not yet available.
    assert h.context_at(datetime(2024, 3, 5, 21, 59, tzinfo=UTC)).risk_regime == "unknown"
    # Tuesday 22:00 UTC: Monday's VIX (14.0) becomes visible.
    ctx = h.context_at(datetime(2024, 3, 5, 22, 0, tzinfo=UTC))
    assert ctx.vix == 14.0
    assert ctx.timestamp == datetime(2024, 3, 5, 22, 0, tzinfo=UTC)


def test_change_pct_and_regime() -> None:
    ctx = fh.FredMacroHistory(CALM).context_at(datetime(2024, 3, 7, 12, 0, tzinfo=UTC))
    assert ctx.vix == 13.0
    assert ctx.vix_change_pct == pytest.approx((13.0 / 14.0 - 1) * 100)
    assert ctx.credit_spread == 3.1
    assert ctx.risk_regime == "risk_on"  # vix<=16, change<=-5%, HY<=3.5
    assert ctx.source_health == 1.0


def test_stale_after_four_days_without_data() -> None:
    ctx = fh.FredMacroHistory(CALM).context_at(datetime(2024, 3, 20, 12, 0, tzinfo=UTC))
    assert ctx.data_stale is True
    assert ctx.risk_regime == "unknown"


def test_missing_series_lowers_health() -> None:
    ctx = fh.FredMacroHistory({fh.VIX: CALM[fh.VIX]}).context_at(
        datetime(2024, 3, 7, 12, 0, tzinfo=UTC))
    assert ctx.source_health == pytest.approx(1 / 3)
    assert ctx.risk_regime == "unknown"  # below the classifier's minimum health


def test_fetch_skips_missing_values_and_hides_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params["series_id"] == "BAD":
            return httpx.Response(400)
        return httpx.Response(200, json={"observations": [
            {"date": "2024-03-04", "value": "14.1"}, {"date": "2024-03-05", "value": "."}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    start = date(2024, 1, 1)
    obs = fh.fetch_series(fh.VIX, "secret-key-123", start, client)
    assert obs == [(date(2024, 3, 4), 14.1)]
    with pytest.raises(RuntimeError) as exc:
        fh.fetch_series("BAD", "secret-key-123", start, client)
    assert "secret-key-123" not in str(exc.value)


def test_save_load_roundtrip(tmp_path: Any) -> None:
    path = tmp_path / "fred.json"
    fh.save(CALM, path)
    assert fh.load(path) == {k: list(v) for k, v in CALM.items()}
