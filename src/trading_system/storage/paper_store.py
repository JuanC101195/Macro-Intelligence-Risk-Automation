"""SQLite persistence for paper trading (ADR 0016).

Standard library only; SQLAlchemy + Alembic arrive with the API (Phase 9). Every write of
one processed bar goes through `transaction()`, so a crash never leaves half a bar applied.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from trading_system.execution.order_intent import OrderIntent

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trades (
    ticket INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id TEXT NOT NULL UNIQUE,
    intent_json TEXT NOT NULL,
    signal_bar_time TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_spread_points INTEGER,
    stop REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    exit_time TEXT,
    exit_price REAL,
    exit_reason TEXT,
    exit_spread_points INTEGER,
    exit_late INTEGER NOT NULL DEFAULT 0,
    pnl REAL
);
CREATE TABLE IF NOT EXISTS signals (
    bar_time TEXT PRIMARY KEY,
    side TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    intent_id TEXT,
    spread_points INTEGER,
    processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bars (
    time TEXT PRIMARY KEY,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


@dataclass(frozen=True)
class PaperTrade:
    ticket: int
    intent: OrderIntent
    signal_bar_time: datetime
    entry_time: datetime
    entry_price: float
    entry_spread_points: int | None
    stop: float
    status: str
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    exit_spread_points: int | None = None
    exit_late: bool = False
    pnl: float | None = None


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _dt(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


class PaperStore:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        version = self.get("schema_version")
        if version is None:
            self.set("schema_version", SCHEMA_VERSION)
        elif int(version) != SCHEMA_VERSION:
            raise RuntimeError(f"paper store schema {version}, code expects {SCHEMA_VERSION}")

    def close(self) -> None:
        self._db.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        self._db.execute("COMMIT")

    # --- key/value state ----------------------------------------------------------------

    def get(self, key: str) -> Any:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else json.loads(row["value"])

    def set(self, key: str, value: Any) -> None:
        self._db.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    # --- trades -------------------------------------------------------------------------

    def open_trade(self, intent: OrderIntent, entry_time: datetime, entry_price: float,
                   spread_points: int | None) -> int:
        cur = self._db.execute(
            "INSERT INTO trades(intent_id, intent_json, signal_bar_time, entry_time, entry_price,"
            " entry_spread_points, stop, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'open')",
            (intent.intent_id, intent.model_dump_json(), _iso(intent.signal_bar_time),
             _iso(entry_time), entry_price, spread_points, intent.stop_loss),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def has_intent(self, intent_id: str) -> bool:
        row = self._db.execute("SELECT 1 FROM trades WHERE intent_id = ?", (intent_id,))
        return row.fetchone() is not None

    def update_stop(self, ticket: int, stop: float) -> None:
        self._db.execute("UPDATE trades SET stop = ? WHERE ticket = ?", (stop, ticket))

    def close_trade(self, ticket: int, *, exit_time: datetime, exit_price: float,
                    reason: str, pnl: float, spread_points: int | None, late: bool) -> None:
        cur = self._db.execute(
            "UPDATE trades SET status = 'closed', exit_time = ?, exit_price = ?,"
            " exit_reason = ?, pnl = ?, exit_spread_points = ?, exit_late = ?"
            " WHERE ticket = ? AND status = 'open'",
            (_iso(exit_time), exit_price, reason, pnl, spread_points, int(late), ticket),
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"trade {ticket} is not open")

    def trades(self, status: str | None = None) -> list[PaperTrade]:
        query = "SELECT * FROM trades"
        args: tuple[Any, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            args = (status,)
        rows = self._db.execute(query + " ORDER BY ticket", args).fetchall()
        return [self._trade(r) for r in rows]

    @staticmethod
    def _trade(r: sqlite3.Row) -> PaperTrade:
        return PaperTrade(
            ticket=r["ticket"], intent=OrderIntent.model_validate_json(r["intent_json"]),
            signal_bar_time=_dt(r["signal_bar_time"]),  # type: ignore[arg-type]
            entry_time=_dt(r["entry_time"]),  # type: ignore[arg-type]
            entry_price=r["entry_price"], entry_spread_points=r["entry_spread_points"],
            stop=r["stop"], status=r["status"], exit_time=_dt(r["exit_time"]),
            exit_price=r["exit_price"], exit_reason=r["exit_reason"],
            exit_spread_points=r["exit_spread_points"], exit_late=bool(r["exit_late"]),
            pnl=r["pnl"],
        )

    # --- signals, bars, runs ------------------------------------------------------------

    def record_signal(self, bar_time: datetime, side: str, outcome: str, detail: str,
                      processed_at: datetime, intent_id: str | None = None,
                      spread_points: int | None = None) -> None:
        self._db.execute(
            "INSERT INTO signals(bar_time, side, outcome, detail, intent_id, spread_points,"
            " processed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_iso(bar_time), side, outcome, detail, intent_id, spread_points,
             _iso(processed_at)),
        )

    def signals(self) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM signals ORDER BY bar_time").fetchall()
        return [dict(r) for r in rows]

    def record_bar(self, time: datetime, o: float, h: float, low: float, c: float) -> None:
        self._db.execute("INSERT INTO bars(time, open, high, low, close) VALUES (?, ?, ?, ?, ?)",
                         (_iso(time), o, h, low, c))

    def record_run(self, time: datetime, status: str, detail: str = "") -> None:
        self._db.execute("INSERT INTO runs(time, status, detail) VALUES (?, ?, ?)",
                         (_iso(time), status, detail))

    def runs(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._db.execute("SELECT * FROM runs ORDER BY id").fetchall()]
