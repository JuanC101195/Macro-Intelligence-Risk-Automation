"""Import rules from docs/architecture.md §2, checked statically over src/.

These rules keep the single path to an order intact:
Signal -> RiskEngine -> OrderIntent -> Executor.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "trading_system"

# package -> module prefixes it must not import
FORBIDDEN: dict[str, tuple[str, ...]] = {
    "config": ("trading_system.broker", "trading_system.strategy", "trading_system.risk",
               "trading_system.execution", "trading_system.models", "trading_system.macro"),
    "broker": ("trading_system.strategy", "trading_system.risk", "trading_system.execution",
               "trading_system.models", "trading_system.macro"),
    "macro": ("trading_system.broker", "trading_system.strategy", "trading_system.risk",
              "trading_system.execution", "trading_system.models"),
    "strategy": ("trading_system.risk", "trading_system.execution", "trading_system.models",
                 "trading_system.broker.mt5_client"),
    "models": ("trading_system.risk", "trading_system.execution"),
    # risk may use execution.order_intent (pure types) but never an executor
    "risk": ("trading_system.execution.paper_executor", "trading_system.execution.demo_executor",
             "trading_system.macro.crucix_client", "trading_system.models"),
    "execution": ("trading_system.strategy", "trading_system.models", "trading_system.macro"),
    "backtest": ("trading_system.broker.mt5_client",),
    # storage persists state; it never decides, sizes or talks to the broker (ADR 0016)
    "storage": ("trading_system.strategy", "trading_system.risk", "trading_system.backtest",
                "trading_system.broker.mt5_client", "trading_system.workers"),
    "api": ("trading_system.broker.mt5_client", "trading_system.broker.orders",
            "trading_system.execution.demo_executor"),
}


def _python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _package_of(path: Path) -> str:
    rel = path.relative_to(SRC)
    return rel.parts[0].removesuffix(".py")


def test_sources_found() -> None:
    assert len(_python_files()) > 5


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_forbidden_imports(path: Path) -> None:
    forbidden = FORBIDDEN.get(_package_of(path), ())
    bad = sorted(
        imp for imp in _imports(path) for prefix in forbidden
        if imp == prefix or imp.startswith(prefix + ".")
    )
    assert not bad, f"{path.relative_to(SRC)} imports forbidden modules: {bad}"


def test_metatrader5_only_in_mt5_client() -> None:
    allowed = SRC / "broker" / "mt5_client.py"
    offenders = [
        str(p.relative_to(SRC)) for p in _python_files()
        if p != allowed and any(i.split(".")[0] == "MetaTrader5" for i in _imports(p))
    ]
    assert not offenders, f"MetaTrader5 imported outside broker/mt5_client.py: {offenders}"


def test_only_the_risk_engine_builds_order_intents() -> None:
    """Single path to an order: Signal -> RiskEngine -> OrderIntent -> Executor."""
    allowed = SRC / "risk" / "engine.py"
    builders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name in {"OrderIntent", "model_construct"} and path != allowed:
                builders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not builders, f"OrderIntent built outside risk/engine.py: {builders}"


def test_no_order_send_anywhere_yet() -> None:
    # Relaxed in Phase 11, and then only for execution/demo_executor.py.
    offenders = [
        str(p.relative_to(SRC)) for p in _python_files()
        if "order_send" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"order_send must not appear before Phase 11: {offenders}"


# ADR 0009: research-lab libraries never enter the package (orders, risk, backtest verdicts).
LAB_ONLY = ("vectorbt", "numba", "sklearn")


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_no_research_lab_imports(path: Path) -> None:
    bad = sorted(m for m in _imports(path) if m.split(".")[0] in LAB_ONLY)
    assert not bad, f"{path.name} imports research-lab libraries {bad} (ADR 0009)"
