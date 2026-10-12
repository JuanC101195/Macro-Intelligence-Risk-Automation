from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fixtures.crucix_payloads import make_payload, risk_off_payload
from trading_system.macro import recorder
from trading_system.macro.crucix_client import CrucixClient, normalize, raw_subset

NOW = datetime(2026, 10, 14, 13, 40, tzinfo=UTC)
FRESH = NOW - timedelta(minutes=10)
MAX_AGE = timedelta(minutes=30)


class TestNormalize:
    def test_full_mapping(self) -> None:
        ctx = normalize(make_payload(FRESH), NOW, MAX_AGE)
        assert ctx.timestamp == FRESH
        assert ctx.vix == 14.8  # live Yahoo value preferred over FRED
        assert ctx.vix_change_pct == -3.9
        assert ctx.yield_curve == 0.42
        assert ctx.credit_spread == 3.2
        assert ctx.oil_change_pct == -1.25
        assert ctx.gold_change_pct == 0.19
        assert ctx.urgent_events == 3
        assert ctx.conflict_events == 312
        assert ctx.source_health == pytest.approx(24 / 27)
        assert ctx.data_stale is False
        assert ctx.risk_regime == "risk_on"

    def test_risk_off(self) -> None:
        assert normalize(risk_off_payload(FRESH), NOW, MAX_AGE).risk_regime == "risk_off"

    def test_vix_falls_back_to_fred(self) -> None:
        ctx = normalize(make_payload(FRESH, markets__vix=None), NOW, MAX_AGE)
        assert ctx.vix == 15.1
        assert ctx.vix_change_pct is None

    def test_stale_payload_is_flagged_and_unknown(self) -> None:
        ctx = normalize(make_payload(NOW - timedelta(hours=2)), NOW, MAX_AGE)
        assert ctx.data_stale is True
        assert ctx.risk_regime == "unknown"

    @pytest.mark.parametrize("bad", [None, [], "oops", 42, {"meta": None}, {"meta": {}},
                                     {"meta": {"timestamp": "not-a-date"}},
                                     {"meta": {"timestamp": "2026-10-14T13:00:00"}}])
    def test_garbage_degrades_to_unknown(self, bad: Any) -> None:
        ctx = normalize(bad, NOW, MAX_AGE)
        assert ctx.risk_regime == "unknown"
        assert ctx.data_stale is True

    def test_future_timestamp_rejected(self) -> None:
        ctx = normalize(make_payload(NOW + timedelta(hours=1)), NOW, MAX_AGE)
        assert ctx.risk_regime == "unknown"

    def test_bad_field_types_become_none(self) -> None:
        payload = make_payload(
            FRESH,
            fred=[{"id": "T10Y2Y", "value": "NaN"}, {"id": "BAMLH0A0HYM2", "value": True}],
            metals__goldChangePct=float("inf"),
            acled__totalEvents=-5,
            tg__urgent="not-a-list",
        )
        ctx = normalize(payload, NOW, MAX_AGE)
        assert ctx.yield_curve is None
        assert ctx.credit_spread is None
        assert ctx.gold_change_pct is None
        assert ctx.conflict_events == 0
        assert ctx.urgent_events == 0

    def test_zero_sources_queried(self) -> None:
        ctx = normalize(make_payload(FRESH, meta__sourcesQueried=0), NOW, MAX_AGE)
        assert ctx.source_health == 0.0
        assert ctx.risk_regime == "unknown"

    def test_real_captured_payload(self) -> None:
        """Real Crucix response (commit 3db7068), captured 2026-10-12 01:20 UTC."""
        path = Path(__file__).resolve().parents[1] / "fixtures" / "crucix_real_20261012.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        captured_at = datetime(2026, 10, 12, 1, 25, tzinfo=UTC)
        ctx = normalize(payload, captured_at, MAX_AGE)
        assert ctx.risk_regime == "risk_on"
        assert ctx.vix == pytest.approx(14.84)
        assert ctx.yield_curve == pytest.approx(0.44)
        assert ctx.credit_spread == pytest.approx(3.15)
        assert ctx.oil_change_pct is not None
        assert ctx.source_health == pytest.approx(27 / 29)
        assert ctx.data_stale is False

    def test_raw_subset_keeps_only_relevant_parts(self) -> None:
        subset = raw_subset(make_payload(FRESH))
        assert set(subset) >= {"meta", "markets", "fred", "tg_urgent_count", "gdelt_counts"}
        assert "news" not in subset


def _client(handler: Callable[[httpx.Request], httpx.Response],
            clock: Callable[[], datetime] = lambda: NOW, **kwargs: Any) -> CrucixClient:
    return CrucixClient("http://crucix.test", transport=httpx.MockTransport(handler),
                        clock=clock, max_age=MAX_AGE, **kwargs)


class TestClient:
    def test_ok(self) -> None:
        client = _client(lambda r: httpx.Response(200, json=make_payload(FRESH)))
        assert client.current().risk_regime == "risk_on"

    def test_first_sweep_in_progress_returns_unknown_after_retries(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(503, json={"error": "No data yet"})

        ctx = _client(handler, retries=2).current()
        assert ctx.risk_regime == "unknown"
        assert len(calls) == 3

    def test_client_error_is_not_retried(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(404)

        assert _client(handler).current().risk_regime == "unknown"
        assert len(calls) == 1

    def test_connection_error_never_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        client = _client(handler)
        assert client.current().risk_regime == "unknown"
        assert client.healthy() is False

    def test_invalid_json_is_unknown(self) -> None:
        client = _client(lambda r: httpx.Response(200, content=b"<html>"))
        assert client.current().risk_regime == "unknown"

    def test_cache_avoids_refetch_within_ttl(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(200, json=make_payload(FRESH))

        client = _client(handler)
        client.current()
        client.current()
        assert len(calls) == 1

    def test_outage_serves_cached_payload_which_goes_stale(self) -> None:
        now = [NOW]
        up = [True]

        def handler(request: httpx.Request) -> httpx.Response:
            if up[0]:
                return httpx.Response(200, json=make_payload(FRESH))
            raise httpx.ConnectError("down")

        client = _client(handler, clock=lambda: now[0])
        assert client.current().risk_regime == "risk_on"
        up[0] = False
        now[0] = NOW + timedelta(hours=1)  # cache TTL expired, Crucix down
        ctx = client.current()
        assert ctx.data_stale is True
        assert ctx.risk_regime == "unknown"

    def test_healthy(self) -> None:
        client = _client(lambda r: httpx.Response(200, json={"status": "ok"}))
        assert client.healthy() is True


class TestRecorder:
    def test_record_and_load(self, tmp_path: Path) -> None:
        client = _client(lambda r: httpx.Response(200, json=make_payload(FRESH)))
        recorder.record_once(client, tmp_path)
        recorder.record_once(client, tmp_path)
        [path] = list(tmp_path.glob("*.jsonl"))
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["classifier"] == "regime-rules-v001"
        assert first["raw"]["fred"][0]["id"] == "T10Y2Y"
        contexts = recorder.load_contexts(path)
        assert contexts[0].vix == 14.8

    def test_single_instance_lock(self, tmp_path: Path) -> None:
        with (
            recorder.single_instance(tmp_path),
            pytest.raises(recorder.AlreadyRunningError),
            recorder.single_instance(tmp_path),
        ):
            pass
        # Released after exit: can be taken again.
        with recorder.single_instance(tmp_path):
            pass

    def test_records_unknown_when_down(self, tmp_path: Path) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        ctx = recorder.record_once(_client(handler), tmp_path)
        assert ctx.risk_regime == "unknown"
        [path] = list(tmp_path.glob("*.jsonl"))
        assert json.loads(path.read_text(encoding="utf-8"))["raw"] is None
