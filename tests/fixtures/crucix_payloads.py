"""Synthetic Crucix /api/data payloads with the real shape (Crucix commit 3db7068).

Values are made up. Replace/extend with captured real responses once Crucix runs
locally (implementation plan task 3.1).
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any


def make_payload(timestamp: datetime, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "meta": {
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "totalDurationMs": 41000,
            "sourcesQueried": 27,
            "sourcesOk": 24,
            "sourcesFailed": 3,
        },
        "markets": {
            "indexes": [{"symbol": "^GSPC", "name": "S&P 500", "price": 6512.3,
                         "change": 20.1, "changePct": 0.31, "history": []}],
            "rates": [],
            "commodities": [
                {"symbol": "CL=F", "name": "WTI Crude", "price": 71.2, "change": -0.9,
                 "changePct": -1.25, "history": []},
                {"symbol": "GC=F", "name": "Gold", "price": 2650.0, "change": 5.0,
                 "changePct": 0.19, "history": []},
            ],
            "crypto": [],
            "vix": {"value": 14.8, "change": -0.6, "changePct": -3.9},
            "timestamp": timestamp.isoformat(),
        },
        "metals": {"gold": 2650.0, "goldChange": 5.0, "goldChangePct": 0.19},
        "fred": [
            {"id": "T10Y2Y", "label": "10Y-2Y Spread (Yield Curve)", "value": 0.42,
             "date": "2026-10-09", "recent": [0.42, 0.40]},
            {"id": "VIXCLS", "label": "VIX (Fear Index)", "value": 15.1, "date": "2026-10-09",
             "recent": [15.1]},
            {"id": "BAMLH0A0HYM2", "label": "High Yield Spread (Credit Stress)", "value": 3.2,
             "date": "2026-10-09", "recent": [3.2]},
        ],
        "energy": {"wti": 71.2, "brent": 74.9, "natgas": 2.9, "signals": []},
        "acled": {"totalEvents": 312, "totalFatalities": 900, "byRegion": {}, "byType": {},
                  "deadliestEvents": []},
        "gdelt": {"totalArticles": 840, "conflicts": 120, "economy": 95, "health": 10,
                  "crisis": 33, "topTitles": [], "geoPoints": []},
        "tg": {"posts": 50, "urgent": [{"channel": "x", "text": "alert", "urgentFlags": []}] * 3,
               "topPosts": []},
        "news": [],
        "ideas": [],
    }
    for dotted, value in overrides.items():
        target = payload
        *parents, leaf = dotted.split("__")
        for key in parents:
            target = target[key]
        target[leaf] = value
    return copy.deepcopy(payload)


def risk_off_payload(timestamp: datetime) -> dict[str, Any]:
    return make_payload(
        timestamp,
        markets__vix={"value": 31.5, "change": 4.2, "changePct": 15.4},
        metals__goldChangePct=2.1,
    )
