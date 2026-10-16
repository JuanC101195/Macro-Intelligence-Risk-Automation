"""ADR 0021: ruptura del rango de apertura en US500 y US30 (`orb-us-v5`, `orb-us-v15`).

Backtest de laboratorio sobre velas M1 (bid + spread). Uso, desde el checkout principal:

    .venv-research\\Scripts\\python.exe research\\lab\\orb_us.py [--nulls 200]

Escribe research/reports/orb_us_result.json (local, ignorado por git).
"""

from __future__ import annotations

import argparse
import glob
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS = ("US500", "US30")
OPEN_MIN, CLOSE_MIN = 9 * 60 + 30, 16 * 60  # hora de Nueva York
RISK, LEVERAGE_CAP = 0.0025, 4.0
MIN_SLIP = 0.1
USD_PER_R = 10.0
VERSIONS = {"orb-us-v5": 5, "orb-us-v15": 15}
NEIGHBOURS = {5: (3, 10), 15: (10, 20)}
TARGETS = (5.0, 15.0)
BASE_TARGET = 10.0


@dataclass
class Day:
    symbol: str
    date: pd.Timestamp
    o: np.ndarray
    h: np.ndarray
    lo: np.ndarray
    c: np.ndarray
    spr: np.ndarray
    mins: np.ndarray


def load_days(symbol: str) -> list[Day]:
    files = sorted(glob.glob(f"research/datasets/{symbol}_M1_20[0-2][0-9]0101_*.parquet"))
    df = pd.concat(pd.read_parquet(f) for f in files).drop_duplicates("time").sort_values("time")
    ny = df["time"].dt.tz_convert("America/New_York")
    df["mins"] = ny.dt.hour * 60 + ny.dt.minute
    df["date"] = ny.dt.normalize()
    df = df[(df["mins"] >= OPEN_MIN) & (df["mins"] < CLOSE_MIN)]
    days = []
    for date, g in df.groupby("date", sort=True):
        days.append(
            Day(
                symbol,
                date,
                g["open"].to_numpy(),
                g["high"].to_numpy(),
                g["low"].to_numpy(),
                g["close"].to_numpy(),
                g["spread_points"].to_numpy() * 0.01,
                g["mins"].to_numpy(),
            )
        )
    return days


def _slip(spr: float, cm: float) -> float:
    return max(0.5 * spr, MIN_SLIP) * cm


def setup(day: Day, n: int) -> tuple[int, int, float, float] | None:
    """(índice de entrada, dirección observada, mínimo y máximo del rango) o None."""
    if day.mins[0] != OPEN_MIN:
        return None
    rng = np.flatnonzero(day.mins < OPEN_MIN + n)
    e = rng[-1] + 1 if rng.size else 0
    if e >= len(day.mins) or day.mins[e] >= OPEN_MIN + n + 5:
        return None
    move = day.c[rng[-1]] - day.o[0]
    side = int(np.sign(move))
    return e, side, float(day.lo[rng].min()), float(day.h[rng].max())


def trade(
    day: Day, e: int, side: int, lo: float, hi: float, target_r: float, cm: float
) -> tuple[float, float, float] | None:
    """Devuelve (r, riesgo como fracción del capital, precio de salida) o None."""
    if side == 0:
        return None
    if side == 1:
        entry = day.o[e] + day.spr[e] * cm + _slip(day.spr[e], cm)
        stop = lo
    else:
        entry = day.o[e] - _slip(day.spr[e], cm)
        stop = hi
    r_pts = side * (entry - stop)
    if r_pts <= day.spr[e]:
        return None
    tp = entry + side * target_r * r_pts
    px = exit_price(day, e, side, stop, tp, cm)
    r = side * (px - entry) / r_pts
    return r, min(RISK, LEVERAGE_CAP * r_pts / entry), px


def exit_price(day: Day, e: int, side: int, stop: float, tp: float, cm: float) -> float:
    w = slice(e, len(day.mins))
    if side == 1:
        lows, highs = day.lo[w], day.h[w]
        hit_sl, hit_tp = np.flatnonzero(lows <= stop), np.flatnonzero(highs >= tp)
    else:
        sp = day.spr[w] * cm
        lows, highs = day.lo[w] + sp, day.h[w] + sp
        hit_sl, hit_tp = np.flatnonzero(highs >= stop), np.flatnonzero(lows <= tp)
    k_sl = hit_sl[0] if hit_sl.size else np.inf
    k_tp = hit_tp[0] if hit_tp.size else np.inf
    if np.isfinite(k_sl) and k_sl <= k_tp:
        k = e + int(k_sl)
        if side == 1:
            return min(stop, day.o[k]) - _slip(day.spr[k], cm)
        return max(stop, day.o[k] + day.spr[k] * cm) + _slip(day.spr[k], cm)
    if np.isfinite(k_tp):
        return tp
    k = len(day.mins) - 1
    if side == 1:
        return day.c[k] - _slip(day.spr[k], cm)
    return day.c[k] + day.spr[k] * cm + _slip(day.spr[k], cm)


def run(
    days: list[Day],
    n: int,
    target_r: float = BASE_TARGET,
    cm: float = 1.0,
    sides: dict[tuple[str, pd.Timestamp], int] | None = None,
) -> pd.DataFrame:
    rows = []
    for d in days:
        s = setup(d, n)
        if s is None:
            continue
        e, side, lo, hi = s
        if sides is not None:
            side = sides.get((d.symbol, d.date), 0) if side != 0 else 0
        t = trade(d, e, side, lo, hi, target_r, cm)
        if t is not None:
            rows.append((d.symbol, d.date, side, t[0], t[1], t[0] * t[1]))
    return pd.DataFrame(rows, columns=["symbol", "date", "side", "r", "risk", "ret"]).sort_values(
        "date"
    )


# ------------------------------------------------------------------------ métricas
def pf(x: np.ndarray) -> float:
    g, lo = x[x > 0].sum(), -x[x < 0].sum()
    return float(g / lo) if lo > 0 else float("inf")


def max_dd(ret: np.ndarray) -> float:
    eq = np.cumprod(1 + ret)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return float(((peak - eq) / peak).max()) if len(ret) else 0.0


def gate(
    base: pd.DataFrame,
    c15: pd.DataFrame,
    c2: pd.DataFrame,
    neighbours: dict[str, pd.DataFrame],
    first: pd.Timestamp,
    last: pd.Timestamp,
) -> dict:
    ret = base["ret"].to_numpy()
    halves = base.groupby([base["date"].dt.year, (base["date"].dt.month - 1) // 6])["ret"].sum()
    years = base.groupby(base["date"].dt.year)["ret"].sum()
    crit = {
        "A1_history_ge_3y": (last - first).days / 365.25 >= 3,
        "A2_trades_ge_300": len(ret) >= 300,
        "A3_expectancy_gt_0": ret.mean() > 0,
        "A4_pf_ge_1_20": pf(ret) >= 1.20,
        "A5_pf_costs15_gt_1": pf(c15["ret"].to_numpy()) > 1.0,
        "A6_windows_pos_ge_60pct": (halves > 0).mean() >= 0.60,
        "A7_dd_le_10pct": max_dd(ret) <= 0.10,
        "A8_without_best_year_gt_0": ret.sum() - years.max() > 0,
        "A9_neighbours_positive": all(nb["ret"].mean() > 0 for nb in neighbours.values()),
    }
    return {
        "criteria": {k: bool(v) for k, v in crit.items()},
        "A1_to_A9_pass": all(crit.values()),
        "summary": {
            "period": [str(first.date()), str(last.date())],
            "trades": len(ret),
            "win_rate": round(float((base["r"] > 0).mean()), 3),
            "pf_costs_1_15_2": [
                round(pf(ret), 3),
                round(pf(c15["ret"].to_numpy()), 3),
                round(pf(c2["ret"].to_numpy()), 3),
            ],
            "expectancy_r": round(float(base["r"].mean()), 4),
            "max_dd_pct": round(max_dd(ret) * 100, 2),
            "positive_halves_pct": round(float((halves > 0).mean() * 100), 1),
            "by_year_pct": {int(k): round(float(v) * 100, 2) for k, v in years.items()},
            "neighbours_expectancy_r": {
                k: round(float(v["r"].mean()), 4) for k, v in neighbours.items()
            },
            "long_share": round(float((base["side"] == 1).mean()), 3),
            "per_symbol_pf": {
                s: round(pf(g["ret"].to_numpy()), 3) for s, g in base.groupby("symbol")
            },
        },
    }


def weekly(base: pd.DataFrame) -> dict:
    iso = base["date"].dt.isocalendar()
    wk = base.assign(y=iso["year"], w=iso["week"]).groupby(["y", "w"])
    ret_w = wk["ret"].sum()
    usd_w = wk["r"].sum() * USD_PER_R
    months = base.groupby([base["date"].dt.year, base["date"].dt.month])
    usd = base["r"].to_numpy() * USD_PER_R
    curve = np.cumsum(usd)
    return {
        "trades_per_week": round(len(base) / len(ret_w), 2),
        "positive_weeks_pct": round(float((ret_w > 0).mean() * 100), 1),
        "worst_week_pct": round(float(ret_w.min() * 100), 2),
        "worst_month_pct": round(float(months["ret"].sum().min() * 100), 2),
        "usd_10_per_trade": {
            "net": round(float(usd.sum()), 1),
            "mean_week": round(float(usd_w.mean()), 2),
            "worst_week": round(float(usd_w.min()), 1),
            "worst_month": round(float((months["r"].sum() * USD_PER_R).min()), 1),
            "worst_drawdown": round(float((curve - np.maximum.accumulate(curve)).min()), 1),
        },
    }


def nulls(days: list[Day], n: int, base: pd.DataFrame, runs: int) -> dict:
    p_long = float((base["side"] == 1).mean())
    keys = list(zip(base["symbol"], base["date"], strict=False))
    obs = pf(base["ret"].to_numpy())
    pfs = []
    for seed in range(runs):
        rng = np.random.default_rng(seed)
        sides = {
            k: (1 if u < p_long else -1) for k, u in zip(keys, rng.random(len(keys)), strict=False)
        }
        pfs.append(pf(run(days, n, sides=sides)["ret"].to_numpy()))
    p95 = float(np.percentile(pfs, 95))
    return {
        "null_pf_p95": round(p95, 3),
        "null_pf_median": round(float(np.median(pfs)), 3),
        "observed_pf": round(obs, 3),
        "beats_p95": bool(obs > p95),
        "p_value": round((1 + sum(p >= obs for p in pfs)) / (runs + 1), 4),
    }


# ------------------------------------------------------------------------- auditoría
def naive_exit(day: Day, e: int, side: int, stop: float, tp: float) -> float:
    for k in range(e, len(day.mins)):
        lo, hi = day.lo[k], day.h[k]
        if side == -1:
            lo, hi = lo + day.spr[k], hi + day.spr[k]
        if (lo <= stop) if side == 1 else (hi >= stop):
            if side == 1:
                return min(stop, day.o[k]) - _slip(day.spr[k], 1.0)
            return max(stop, day.o[k] + day.spr[k]) + _slip(day.spr[k], 1.0)
        if (hi >= tp) if side == 1 else (lo <= tp):
            return tp
    k = len(day.mins) - 1
    return (
        day.c[k] - _slip(day.spr[k], 1.0)
        if side == 1
        else day.c[k] + day.spr[k] + _slip(day.spr[k], 1.0)
    )


def audit(days: list[Day], n: int) -> dict:
    rng = np.random.default_rng(7)
    diffs = []
    for i in rng.choice(len(days), size=200, replace=False):
        d = days[i]
        s = setup(d, n)
        if s is None or s[1] == 0:
            continue
        e, side, lo, hi = s
        t = trade(d, e, side, lo, hi, BASE_TARGET, 1.0)
        if t is None:
            continue
        entry = (
            d.o[e] + d.spr[e] + _slip(d.spr[e], 1.0) if side == 1 else d.o[e] - _slip(d.spr[e], 1.0)
        )
        stop = lo if side == 1 else hi
        tp = entry + side * BASE_TARGET * side * (entry - stop)
        diffs.append(abs(naive_exit(d, e, side, stop, tp) - t[2]))
        if len(diffs) == 20:
            break
    return {"checked": len(diffs), "mismatches": int(sum(x > 1e-9 for x in diffs))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nulls", type=int, default=200)
    args = ap.parse_args()
    days = sorted((d for s in SYMBOLS for d in load_days(s)), key=lambda d: d.date)
    first = max(min(d.date for d in days if d.symbol == s) for s in SYMBOLS)
    days = [d for d in days if d.date >= first]
    last = days[-1].date
    result: dict = {"adr": "0021", "symbols": SYMBOLS, "days": len(days)}
    for name, n in VERSIONS.items():
        base = run(days, n)
        nbs = {f"range={m}": run(days, m) for m in NEIGHBOURS[n]}
        nbs |= {f"target={t:g}R": run(days, n, target_r=t) for t in TARGETS}
        g = gate(base, run(days, n, cm=1.5), run(days, n, cm=2.0), nbs, first, last)
        g["weekly"] = weekly(base)
        g["audit"] = audit(days, n)
        long_all = run(days, n, sides={(d.symbol, d.date): 1 for d in days})
        g["control_always_long"] = {
            "trades": len(long_all),
            "pf": round(pf(long_all["ret"].to_numpy()), 3),
        }
        if args.nulls and g["A1_to_A9_pass"]:
            g["A11"] = nulls(days, n, base, args.nulls)
        else:
            g["A11"] = "no corrido (A1–A9 no pasan)" if args.nulls else "no pedido"
        result[name] = g
    out = Path("research/reports/orb_us_result.json")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
