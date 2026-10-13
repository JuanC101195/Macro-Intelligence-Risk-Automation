"""Markdown rendering of a research report (research/reports/, local only)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ICON = {"pass": "✓", "fail": "✗", "pending": "…"}
SEP4 = "|---|---|---|---|"


def _fmt(value: Any, pct: bool = False) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2%}" if pct else f"{value:,.2f}"
    return str(value)


def _null_section(null: Mapping[str, Any] | None) -> list[str]:
    if not null:
        return []
    pf = null["null_pf"]
    return [
        f"## Random entries (ADR 0010, {null['runs']} versions)", "",
        f"- Null profit factor: p5 {_fmt(pf['p5'])} · median {_fmt(pf['median'])} · "
        f"p95 {_fmt(pf['p95'])}; null trades {null['null_trades']['min']}–"
        f"{null['null_trades']['max']}",
        f"- Observed rank: profit factor {null['rank_pf']:.0%}, expectancy "
        f"{null['rank_expectancy']:.0%}; p-value (PF) {null['p_value_pf']:.3f}", "",
    ]


def render(report: Mapping[str, Any]) -> str:
    m = report["metrics"]
    base = m["costs_x1"]
    p = report["period"]
    lines = [
        f"# Backtest {report['strategy']['version']} — {report['label']}",
        "",
        "> Not financial advice. Results include modelled costs; see assumptions. A good",
        "> backtest is not evidence of an edge until the ADR 0002 gates pass.",
        "",
        f"- Period: {p['start'][:10]} → {p['end'][:10]} "
        f"(hold-out starts {p['holdout_start'][:10]})",
        f"- Symbols: {', '.join(report['symbols'])}",
        f"- Config: `{report['config_fingerprint']}` · trades digest `{report['trades_digest']}`",
        "",
        "## Gate A (ADR 0002)",
        "",
        "| | Criterion | Threshold | Value | |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {c['id']} | {c['criterion']} | {c['threshold']} | {c['value']} | "
              f"{ICON[c['status']]} |" for c in report["gate_a"]]
    lines += ["", f"**Gate A passed: {'YES' if report['gate_a_passed'] else 'NO'}**", ""]
    lines += _null_section(report.get("null_model"))
    lines += ["## Summary by cost scenario", "",
              "| Metric | costs x1 | costs x1.5 | costs x2 |", SEP4]
    rows = [("Trades", "trades", False), ("Net profit", "net_profit", False),
            ("Return", "return_pct", True), ("Profit factor", "profit_factor", False),
            ("Expectancy / trade", "expectancy", False), ("Expectancy (R)", "expectancy_r", False),
            ("Win rate", "win_rate", True), ("Max drawdown", "max_drawdown_pct", True),
            ("Sharpe", "sharpe", False), ("Sortino", "sortino", False)]
    for title, key, pct in rows:
        lines.append(f"| {title} | " + " | ".join(
            _fmt(m[s][key], pct) for s in ("costs_x1", "costs_x1.5", "costs_x2")) + " |")
    lines += ["", "## Walk-forward windows (costs x1)", "",
              "| Window | Trades | Net | PF |", SEP4]
    lines += [f"| {w['start']} → {w['end']} | {w['trades']} | {_fmt(w['net_profit'])} | "
              f"{_fmt(w['profit_factor'])} |" for w in report["walk_forward"]]
    for title, key in (("By symbol", "by_symbol"), ("By session (entry, UTC)", "by_session"),
                       ("By year", "by_year")):
        lines += ["", f"## {title}", "", "| | Trades | Net | PF |", SEP4]
        lines += [f"| {k} | {v['trades']} | {_fmt(v['net'])} | {_fmt(v['profit_factor'])} |"
                  for k, v in base[key].items()]
    lines += ["", "## Exits, rejections, holds", "",
              f"- Exit reasons: {base['exit_reasons']}",
              f"- Rejected by risk: {base['rejected_by_risk']}",
              f"- Fills cancelled across data gaps: {base['cancelled_fills_gap']}",
              f"- Top hold reasons: {base['hold_reasons']}",
              f"- Time in market: {_fmt(base['time_in_market_pct'], True)}",
              f"- Max consecutive losses: {base['max_consecutive_losses']}",
              "", "## Neighbour variants (A9) — expectancy per trade", ""]
    variants = report["neighbours_expectancy"]
    lines += [f"- {k}: {_fmt(v)}" for k, v in variants.items()] or ["- not run"]
    lines += ["", "## Assumptions", ""] + [f"- {a}" for a in report["assumptions"]]
    return "\n".join(lines) + "\n"
