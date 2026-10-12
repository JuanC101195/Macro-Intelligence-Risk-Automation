"""Macro snapshot recorder (implementation plan task 3.6, docs/architecture.md §5.3).

Crucix has no queryable history, so these snapshots ARE the macro history the
backtest and the ML features will use. One JSON line per snapshot, one file per
month. Stays local (gitignored) while the repo is public (ADR 0001 #14).
Moves to the database in Phase 7.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from trading_system.macro import regime_classifier
from trading_system.macro.crucix_client import CrucixClient, normalize, raw_subset
from trading_system.macro.macro_context import MacroContext

DEFAULT_DIR = Path("research/macro_snapshots")


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


__all__ = ["DEFAULT_DIR", "load_contexts", "normalize", "record_once"]
