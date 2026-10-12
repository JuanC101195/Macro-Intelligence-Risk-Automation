"""Macro snapshot recorder (implementation plan task 3.6, docs/architecture.md §5.3).

Crucix has no queryable history, so these snapshots ARE the macro history the
backtest and the ML features will use. One JSON line per snapshot, one file per
month. Stays local (gitignored) while the repo is public (ADR 0001 #14).
Moves to the database in Phase 7.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from trading_system.macro import regime_classifier
from trading_system.macro.crucix_client import CrucixClient, normalize, raw_subset
from trading_system.macro.macro_context import MacroContext

DEFAULT_DIR = Path("research/macro_snapshots")


class AlreadyRunningError(RuntimeError):
    """Another recorder holds the lock for this output directory."""


@contextmanager
def single_instance(out_dir: Path) -> Iterator[None]:
    """Exclusive, OS-level lock per output directory.

    Two recorders writing the same files would duplicate snapshots. The lock is
    released by the OS if the process dies, so a crash never leaves it stuck.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    fh = (out_dir / ".recorder.lock").open("a+b")
    try:
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise AlreadyRunningError(f"another recorder is already writing to {out_dir}") from None
        yield
    finally:
        fh.close()


def wait_for_data(
    client: CrucixClient,
    timeout: timedelta,
    poll: timedelta = timedelta(seconds=15),
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Poll until Crucix serves /api/data. Avoids an empty first snapshot after a restart."""
    deadline = time.monotonic() + timeout.total_seconds()
    while True:
        if client.fetch_raw() is not None:
            return True
        if time.monotonic() >= deadline:
            return False
        sleep(poll.total_seconds())


def record_once(client: CrucixClient, out_dir: Path = DEFAULT_DIR) -> MacroContext:
    payload = client.fetch_raw()
    now = datetime.now(UTC)
    context = client.current()
    line = {
        "recorded_at": now.isoformat(),
        "classifier": regime_classifier.VERSION,
        "context": context.model_dump(mode="json"),
        "raw": raw_subset(payload) if payload is not None else None,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{now:%Y-%m}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, separators=(",", ":"), default=str) + "\n")
    return context


def load_contexts(path: Path) -> list[MacroContext]:
    """Read back recorded contexts (for the backtest's as-of lookup)."""
    contexts = []
    with path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            if raw_line.strip():
                contexts.append(MacroContext(**json.loads(raw_line)["context"]))
    return contexts


__all__ = [
    "DEFAULT_DIR",
    "AlreadyRunningError",
    "load_contexts",
    "normalize",
    "record_once",
    "single_instance",
    "wait_for_data",
]
