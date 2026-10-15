"""ADR 0018: reversión de corto plazo en oro, estilo del socio (`fade-xau-v001`).

Backtest vectorizado de laboratorio sobre XAUUSD M1 (precio bid + spread por vela).
Uso, desde el checkout principal y con el entorno de laboratorio:

    .venv-research\\Scripts\\python.exe research\\lab\\fade_xau.py [--audit] [--nulls 200]

Lee research/datasets/XAUUSD_M1_<año>0101_*.parquet y escribe
research/reports/fade_xau_result.json (local, ignorado por git).
"""

from __future__ import annotations

import argparse
import glob
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DATA_GLOB = "research/datasets/XAUUSD_M1_20[0-2][0-9]0101_*.parquet"
CUTOFF = pd.Timestamp("2026-09-24", tz="UTC")  # el periodo del socio queda fuera
SESSION_HOURS = (4, 5, 6, 12, 13, 14, 15, 16)
LOOKBACK_MIN = 60
RANGE_BARS = 240
D_DAYS = 20
POS_LONG, POS_SHORT = 0.35, 0.65
TP_D = 0.45
TIME_STOP_MIN = 120
COOLDOWN_MIN = 5
SLIP = 0.05
COMMISSION = 0.10  # 10 USD por lote ida y vuelta = 0.10 USD por onza
RISK = 0.0025
KS = (0.7, 1.0)
SS = (0.75, 1.5)
DIRS = ("both", "long")
FIRST_TEST_YEAR, TRAIN_YEARS, MIN_TRAIN_TRADES = 2013, 3, 100
NS = 1_000_000_000 * 60  # nanosegundos por minuto
OUTPUTS = {"base": Path("research/reports/fade_xau_result_base.json"),
           "stop3": Path("research/reports/fade_xau_result_stop3.json")}


# --------------------------------------------------------------------------- datos
@dataclass
class Market:
    t: np.ndarray  # int64 ns UTC
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    spr: np.ndarray  # USD
    ret60: np.ndarray
    pos4h: np.ndarray
    d: np.ndarray  # D vigente para la vela (NaN si no hay 20 días previos)
    session: np.ndarray
    year: np.ndarray


def load_market() -> Market:
    frames = [pd.read_parquet(p) for p in sorted(glob.glob(DATA_GLOB))]
    df = pd.concat(frames).drop_duplicates("time").sort_values("time")
    df = df[df["time"] < CUTOFF].reset_index(drop=True)
    t = df["time"].dt.as_unit("ns").astype("int64").to_numpy()  # el parquet viene en ms
    c = df["close"].to_numpy()
    prev = np.searchsorted(t, t - LOOKBACK_MIN * NS, side="right") - 1
    ret60 = np.where(prev >= 0, c - c[np.clip(prev, 0, None)], np.nan)
    hi = df["high"].rolling(RANGE_BARS).max().shift(1).to_numpy()
    lo = df["low"].rolling(RANGE_BARS).min().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        pos4h = np.where(hi > lo, (c - lo) / (hi - lo), np.nan)
    hours = df["time"].dt.hour.to_numpy()
    session = np.isin(hours, SESSION_HOURS)
    d = daily_d(df["time"].dt.date.to_numpy(), np.abs(ret60), session)
    return Market(t, df["open"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy(), c,
                  df["spread_points"].to_numpy() * 0.01, ret60, pos4h, d, session,
                  df["time"].dt.year.to_numpy())


def daily_d(dates: np.ndarray, absret: np.ndarray, session: np.ndarray) -> np.ndarray:
    """D de cada día = mediana de |ret60| en sesión de los 20 días hábiles previos."""
    uniq, start = np.unique(dates, return_index=True)
    bounds = list(start) + [len(dates)]
    per_day = []
    for i in range(len(uniq)):
        seg = slice(bounds[i], bounds[i + 1])
        vals = absret[seg][session[seg]]
        per_day.append(vals[~np.isnan(vals)])
    out = np.full(len(dates), np.nan)
    for i in range(D_DAYS, len(uniq)):
        pool = np.concatenate(per_day[i - D_DAYS:i])
        if pool.size:
            out[bounds[i]:bounds[i + 1]] = np.median(pool)
    return out


# --------------------------------------------------------------------- simulación
@dataclass(frozen=True)
class Variant:
    k: float
    s: float | None  # None = sin stop (informativa)
    direction: str
    time_stop: int = TIME_STOP_MIN
    tp_d: float = TP_D

    @property
    def name(self) -> str:
        base = f"k{self.k}-s{self.s}-{self.direction}"
        return base if self.tp_d == TP_D else f"{base}-tp{self.tp_d}"


def family(kind: str) -> list[Variant]:
    if kind == "stop3":  # adenda 2: stop = TP / 3
        return [Variant(k, round(tp / 3, 4), d, tp_d=tp) for k in KS for tp in (0.45, 1.41) for d in DIRS]
    return [Variant(k, s, d) for k in KS for s in SS for d in DIRS]


def signals(m: Market, v: Variant) -> np.ndarray:
    """+1 compra, -1 venta, 0 nada, al cierre de cada vela."""
    ok = m.session & ~np.isnan(m.d) & ~np.isnan(m.pos4h)
    with np.errstate(invalid="ignore"):
        long_ = ok & (m.ret60 <= -v.k * m.d) & (m.pos4h <= POS_LONG)
        short = ok & (m.ret60 >= v.k * m.d) & (m.pos4h >= POS_SHORT)
    sig = np.where(long_, 1, 0)
    if v.direction == "both":
        sig = np.where(short, -1, sig)
    return sig


def _first(hits: np.ndarray) -> float:
    return float(hits[0]) if hits.size else np.inf


def _quotes(m: Market, w: slice, side: int, cost_mult: float) -> tuple[np.ndarray, np.ndarray]:
    """Mínimos y máximos del precio de salida: bid para compras, ask para ventas."""
    if side == 1:
        return m.l[w], m.h[w]
    sp = m.spr[w] * cost_mult
    return m.l[w] + sp, m.h[w] + sp


def _stop_fill(m: Market, k: int, side: int, sl: float, cost_mult: float) -> float:
    """Stop a mercado: si la vela abre más allá del stop, se llena en la apertura."""
    slip = SLIP * cost_mult
    if side == 1:
        return min(sl, m.o[k]) - slip
    return max(sl, m.o[k] + m.spr[k] * cost_mult) + slip


def _close_fill(m: Market, k: int, side: int, cost_mult: float) -> float:
    slip = SLIP * cost_mult
    if side == 1:
        return m.c[k] - slip
    return m.c[k] + m.spr[k] * cost_mult + slip


def exit_trade(m: Market, j: int, side: int, entry: float, tp: float, sl: float | None,
               time_stop: int, cost_mult: float) -> tuple[int, float, float]:
    """Devuelve (índice de salida, precio de salida, peor excursión en contra)."""
    end = np.searchsorted(m.t, m.t[j] + time_stop * NS, side="left")
    w = slice(j, max(end, j + 1))
    lows, highs = _quotes(m, w, side, cost_mult)
    first_tp = _first(np.flatnonzero(highs >= tp) if side == 1 else np.flatnonzero(lows <= tp))
    first_sl = np.inf
    if sl is not None:
        first_sl = _first(np.flatnonzero(lows <= sl) if side == 1 else np.flatnonzero(highs >= sl))
    if np.isfinite(first_sl) and first_sl <= first_tp:  # empate -> stop (conservador)
        k = int(first_sl)
        px = _stop_fill(m, j + k, side, sl, cost_mult)  # type: ignore[arg-type]
    elif np.isfinite(first_tp):
        k = int(first_tp)
        px = tp
    else:
        k = w.stop - w.start - 1
        px = _close_fill(m, j + k, side, cost_mult)
    adverse = (entry - lows[: k + 1].min()) if side == 1 else (highs[: k + 1].max() - entry)
    return j + k, float(px), float(max(adverse, 0.0))


def _trade_side(signal: int, rng: np.random.Generator | None, p_long: float) -> int:
    if rng is None:
        return signal
    return 1 if rng.random() < p_long else -1


def _entry_price(m: Market, j: int, side: int, cost_mult: float) -> float:
    slip = SLIP * cost_mult
    if side == 1:
        return m.o[j] + m.spr[j] * cost_mult + slip
    return m.o[j] - slip


def simulate(m: Market, sig: np.ndarray, v: Variant, cost_mult: float = 1.0,
             rng: np.random.Generator | None = None, p_long: float = 0.5) -> pd.DataFrame:
    """Recorre las señales en orden, una posición a la vez."""
    cand = np.flatnonzero(sig != 0)
    rows = []
    free_at = -1
    n = len(m.t)
    for i in cand:
        if m.t[i] < free_at or i + 1 >= n or m.t[i + 1] - m.t[i] > 5 * NS:
            continue
        side = _trade_side(int(sig[i]), rng, p_long)
        j = i + 1
        d = m.d[i]
        entry = _entry_price(m, j, side, cost_mult)
        tp = entry + side * v.tp_d * d
        sl = None if v.s is None else entry - side * v.s * d
        x, px, mae = exit_trade(m, j, side, entry, tp, sl, v.time_stop, cost_mult)
        pnl = side * (px - entry) - COMMISSION * cost_mult
        risk = (v.s * d) if v.s is not None else d
        rows.append((m.t[j], m.t[x], m.year[j], side, entry, px, pnl, pnl / risk, mae, d))
        free_at = m.t[x] + COOLDOWN_MIN * NS
    return pd.DataFrame(rows, columns=["t_in", "t_out", "year", "side", "entry", "exit",
                                       "pnl", "r", "mae", "d"])


# ------------------------------------------------------------------------ métricas
def pf(x: np.ndarray) -> float:
    g, lo = x[x > 0].sum(), -x[x < 0].sum()
    return float(g / lo) if lo > 0 else float("inf")


def max_dd_pct(r: np.ndarray) -> float:
    eq = np.cumprod(1 + RISK * r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return float(((peak - eq) / peak).max() * 100) if len(r) else 0.0


def walk_forward(trades: dict[str, pd.DataFrame], last_year: int) -> dict[int, str]:
    chosen = {}
    for y in range(FIRST_TEST_YEAR, last_year + 1):
        best, best_pf = None, -1.0
        for name, tr in trades.items():
            sub = tr[(tr["year"] >= y - TRAIN_YEARS) & (tr["year"] < y)]
            if len(sub) < MIN_TRAIN_TRADES:
                continue
            p = pf(sub["r"].to_numpy())
            if p > best_pf:
                best, best_pf = name, p
        if best is not None:
            chosen[y] = best
    return chosen


def oos(trades: dict[str, pd.DataFrame], chosen: dict[int, str]) -> pd.DataFrame:
    parts = [trades[n][trades[n]["year"] == y] for y, n in chosen.items()]
    return pd.concat(parts).sort_values("t_in") if parts else pd.DataFrame()


def neighbours(name: str, variants: list[Variant]) -> list[str]:
    """Variantes que difieren en una sola dimensión de la rejilla (k o stop/TP), misma dirección."""
    me = next(v for v in variants if v.name == name)
    out = []
    for v in variants:
        if v.direction != me.direction or v.name == name:
            continue
        same_k = v.k == me.k
        same_exit = (v.s, v.tp_d) == (me.s, me.tp_d)
        if same_k != same_exit:
            out.append(v.name)
    return out


def gate(oos1: pd.DataFrame, oos15: pd.DataFrame, trades: dict[str, pd.DataFrame],
         chosen: dict[int, str], null_p95: float | None, variants: list[Variant]) -> dict:
    r = oos1["r"].to_numpy()
    by_year = oos1.groupby("year")["r"].sum()
    best_year = by_year.idxmax() if len(by_year) else None
    years = sorted(chosen)
    nb_ok = True
    for name in set(chosen.values()):
        for nb in neighbours(name, variants):
            sub = trades[nb][trades[nb]["year"].isin(years)]
            nb_ok &= bool(len(sub)) and sub["r"].mean() > 0
    crit = {
        "A2_trades_ge_300": len(r) >= 300,
        "A3_expectancy_gt_0": r.mean() > 0 if len(r) else False,
        "A4_pf_ge_1_20": pf(r) >= 1.20,
        "A5_pf_costs15_gt_1": pf(oos15["r"].to_numpy()) > 1.0,
        "A6_windows_pos_ge_60pct": (by_year > 0).mean() >= 0.60 if len(by_year) else False,
        "A7_dd_le_10pct": max_dd_pct(r) <= 10.0,
        "A8_without_best_year_gt_0": (r.sum() - by_year.max()) > 0 if len(by_year) else False,
        "A9_neighbours_positive": nb_ok,
        "A10": "no evaluado (hold-out ya usado)",
        "A11_beats_null_p95": (pf(r) > null_p95) if null_p95 is not None else "pendiente",
    }
    passed = all(v is True for k, v in crit.items() if k != "A10")
    return {"criteria": {k: (bool(v) if isinstance(v, (bool, np.bool_)) else v) for k, v in crit.items()},
            "passes_gate_A": passed,
            "summary": {"trades": int(len(r)), "pf": round(pf(r), 3),
                        "expectancy_r": round(float(r.mean()), 4) if len(r) else None,
                        "net_r": round(float(r.sum()), 1), "dd_pct_0_25": round(max_dd_pct(r), 2),
                        "pf_costs_1_5": round(pf(oos15["r"].to_numpy()), 3),
                        "best_year": int(best_year) if best_year is not None else None,
                        "by_year_r": {int(k): round(float(v), 1) for k, v in by_year.items()},
                        "long_share": round(float((oos1["side"] == 1).mean()), 3)}}


# --------------------------------------------------------------------------- nulos
_M: Market | None = None
_IDX: dict[int, np.ndarray] = {}


def _init_worker() -> None:
    global _M
    _M = load_market()
    ok = _M.session & ~np.isnan(_M.d)
    for y in np.unique(_M.year):
        _IDX[int(y)] = np.flatnonzero(ok & (_M.year == y))


def _null_run(args: tuple[int, dict[int, tuple[Variant, float, float]]]) -> float:
    seed, plan = args
    assert _M is not None
    m = _M
    rng = np.random.default_rng(seed)
    rs = []
    for y, (v, p_entry, p_long) in plan.items():
        idx = _IDX[y]
        sig = np.zeros(len(m.t), dtype=int)
        sig[idx[rng.random(len(idx)) < p_entry]] = 1
        tr = simulate(m, sig, v, rng=rng, p_long=p_long)
        rs.append(tr["r"].to_numpy())
    return pf(np.concatenate(rs)) if rs else 0.0


def null_plan(m: Market, trades: dict[str, pd.DataFrame], chosen: dict[int, str],
              by_name: dict[str, Variant]) -> dict:
    plan = {}
    for y, name in chosen.items():
        tr = trades[name][trades[name]["year"] == y]
        sess = m.session & ~np.isnan(m.d) & (m.year == y)
        busy = ((tr["t_out"] - tr["t_in"]) / NS + COOLDOWN_MIN).sum()
        free = max(sess.sum() - busy, 1)
        plan[y] = (by_name[name], len(tr) / free, float((tr["side"] == 1).mean()) if len(tr) else 0.5)
    return plan


# -------------------------------------------------------------------- informativa
def partner_style(m: Market) -> dict:
    v = Variant(0.7, None, "both", time_stop=1440)
    tr = simulate(m, signals(m, v), v)
    usd = tr["pnl"].to_numpy() * 3.0  # 0.03 lotes x 100 onzas = 3 onzas
    mae = tr["mae"].to_numpy() * 3.0
    eq = 8400 + np.cumsum(usd)
    day = pd.Series(usd, index=pd.to_datetime(tr["t_out"], utc=True)).groupby(lambda x: x.date()).sum()
    month = pd.Series(usd, index=pd.to_datetime(tr["t_out"], utc=True)).groupby(lambda x: (x.year, x.month)).sum()
    peak = np.maximum.accumulate(np.concatenate([[8400.0], eq]))[1:]
    return {"trades": int(len(tr)), "net_usd": round(float(usd.sum()), 2), "pf": round(pf(usd), 3),
            "win_rate": round(float((usd > 0).mean()), 3),
            "worst_trade_usd": round(float(usd.min()), 2), "worst_open_loss_usd": round(float(mae.max()), 2),
            "worst_day_usd": round(float(day.min()), 2), "worst_month_usd": round(float(month.min()), 2),
            "max_dd_usd": round(float((peak - eq).max()), 2),
            "min_equity_usd": round(float(eq.min()), 2), "survived": bool(eq.min() > 0),
            "by_year_usd": {int(y): round(float(v), 0) for y, v in pd.Series(usd).groupby(tr["year"].to_numpy()).sum().items()}}


# ------------------------------------------------------------------------- auditoría
def _naive_hits(m: Market, k: int, side: int, tp: float, sl: float) -> tuple[bool, bool]:
    """(stop tocado, objetivo tocado) en la vela k, con el precio de salida de cada lado."""
    lo, hi = m.l[k], m.h[k]
    if side == 1:
        return bool(lo <= sl), bool(hi >= tp)
    lo, hi = lo + m.spr[k], hi + m.spr[k]
    return bool(hi >= sl), bool(lo <= tp)


def naive_exit(m: Market, j: int, side: int, tp: float, sl: float) -> float:
    """Bucle vela a vela, independiente de exit_trade."""
    limit = m.t[j] + TIME_STOP_MIN * NS
    last = j
    while last + 1 < len(m.t) and m.t[last + 1] < limit:
        last += 1
    for k in range(j, last + 1):
        sl_hit, tp_hit = _naive_hits(m, k, side, tp, sl)
        if sl_hit and side == 1:
            return min(sl, m.o[k]) - SLIP
        if sl_hit:
            return max(sl, m.o[k] + m.spr[k]) + SLIP
        if tp_hit:
            return tp
    if side == 1:
        return m.c[last] - SLIP
    return m.c[last] + m.spr[last] + SLIP


def audit(m: Market, trades: pd.DataFrame, v: Variant, n: int = 20) -> dict:
    rng = np.random.default_rng(7)
    sample = trades.iloc[rng.choice(len(trades), size=min(n, len(trades)), replace=False)]
    diffs = []
    for _, tr in sample.iterrows():
        j = int(np.searchsorted(m.t, tr["t_in"]))
        side = int(tr["side"])
        tp = tr["entry"] + side * v.tp_d * tr["d"]
        sl = tr["entry"] - side * v.s * tr["d"]
        diffs.append(abs(naive_exit(m, j, side, tp, sl) - tr["exit"]))
    return {"checked": len(diffs), "max_abs_diff": round(float(max(diffs)), 6),
            "mismatches": int(sum(d > 1e-6 for d in diffs))}


# ------------------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nulls", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--family", choices=("base", "stop3"), default="base")
    args = ap.parse_args()
    m = load_market()
    variants = family(args.family)
    by_name = {v.name: v for v in variants}
    t1 = {v.name: simulate(m, signals(m, v), v) for v in variants}
    t15 = {v.name: simulate(m, signals(m, v), v, cost_mult=1.5) for v in variants}
    last_year = int(m.year.max())
    chosen = walk_forward(t1, last_year)
    o1, o15 = oos(t1, chosen), oos(t15, chosen)
    result: dict = {
        "adr": "0018", "bars": int(len(m.t)),
        "data_start": str(pd.Timestamp(m.t[0], tz="UTC")), "data_end": str(pd.Timestamp(m.t[-1], tz="UTC")),
        "variants_full_period": {n: {"trades": len(t), "pf": round(pf(t["r"].to_numpy()), 3),
                                     "expectancy_r": round(float(t["r"].mean()), 4)}
                                 for n, t in t1.items()},
        "chosen_by_year": chosen,
        "audit": {variants[0].name: audit(m, t1[variants[0].name], variants[0])},
    }
    null_p95 = None
    r_oos = o1["r"].to_numpy()
    worth_nulls = len(r_oos) > 0 and r_oos.mean() > 0 and pf(r_oos) >= 1.20  # A11 solo si A3 y A4
    if args.nulls and worth_nulls:
        plan = null_plan(m, t1, chosen, by_name)
        with ProcessPoolExecutor(args.workers, initializer=_init_worker) as ex:
            null_pfs = list(ex.map(_null_run, [(s, plan) for s in range(args.nulls)]))
        null_p95 = float(np.percentile(null_pfs, 95))
        obs = pf(o1["r"].to_numpy())
        result["A11"] = {"null_pf_p95": round(null_p95, 3), "null_pf_median": round(float(np.median(null_pfs)), 3),
                         "observed_pf": round(obs, 3),
                         "p_value": round((1 + sum(p >= obs for p in null_pfs)) / (len(null_pfs) + 1), 4)}
    result["gate_A"] = gate(o1, o15, t1, chosen, null_p95, variants)
    if args.family == "base":
        result["partner_style_no_stop"] = partner_style(m)
    out = OUTPUTS[args.family]  # rutas fijas: nada del usuario entra en la ruta
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
