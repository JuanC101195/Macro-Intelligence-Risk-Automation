"""ADR 0013: evaluación del historial real del socio (oro discrecional).

Uso (desde el checkout principal, con el entorno de laboratorio):

    .venv-research\\Scripts\\python.exe research\\lab\\partner_history.py \\
        research\\reports\\partner\\ReportHistory-XXXX.xlsx \\
        research\\datasets\\XAUUSD_M5_20260915_20261016.parquet

Lee el informe de MT5 (hoja única, sección "Posiciones"), alinea cada posición
con nuestras velas M5 y calcula las métricas, los nulos N1/N2 y el veredicto
pre-registrados en la ADR 0013. El resultado se guarda en
research/reports/partner/ (ignorado por git). No imprime datos de la cuenta.
"""

from __future__ import annotations

import json
import sys
import warnings
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

GOLD_PREFIX = "XAUUSD"
CONTRACT_OZ = 100.0
POINT = 0.01
PRICE_TOLERANCE = 1.5
MATCH_MIN = 0.90
SERVER_OFFSET_H = 3
N_SIMS = 10_000
SEED = 13
INITIAL_BALANCE_LABEL = "Deposit"


@dataclass
class Report:
    positions: pd.DataFrame
    initial_deposit: float


def _num(value: object) -> float:
    if value is None or value == "":
        return 0.0
    return float(str(value).replace(" ", ""))


def read_report(path: Path) -> Report:
    warnings.filterwarnings("ignore")
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    first = [i for i, r in enumerate(rows) if r[0] == "Posiciones"][0] + 2
    records = []
    for r in rows[first:]:
        if not r[0] or not str(r[0])[:4].isdigit():
            break
        records.append(
            {
                "open_time": pd.Timestamp(str(r[0]).replace(".", "-")),
                "symbol": r[2],
                "side": r[3],
                "volume": _num(r[4]),
                "open_price": _num(r[5]),
                "sl": _num(r[6]),
                "tp": _num(r[7]),
                "close_time": pd.Timestamp(str(r[8]).replace(".", "-")),
                "close_price": _num(r[9]),
                "commission": _num(r[10]),
                "swap": _num(r[11]),
                "profit": _num(r[12]),
            }
        )
    deposit = 0.0
    for r in rows:
        vals = [v for v in r if v is not None]
        if vals and vals[-1] == INITIAL_BALANCE_LABEL and deposit == 0.0:
            deposit = _num(vals[-3])
    pos = pd.DataFrame(records)
    pos["net"] = pos["profit"] + pos["commission"] + pos["swap"]
    pos["dir"] = np.where(pos["side"] == "buy", 1, -1)
    return Report(pos, deposit)


def to_bar_index(times: pd.Series, bars: pd.DataFrame, offset_h: int) -> np.ndarray:
    utc = (times - timedelta(hours=offset_h)).dt.tz_localize("UTC").dt.floor("5min")
    idx = bars.index.get_indexer(utc)
    return idx


def alignment(pos: pd.DataFrame, bars: pd.DataFrame, offset_h: int) -> float:
    idx = to_bar_index(pos["open_time"], bars, offset_h)
    ok = idx >= 0
    lo = bars["low"].to_numpy()[idx[ok]] - PRICE_TOLERANCE
    hi = bars["high"].to_numpy()[idx[ok]] + PRICE_TOLERANCE
    price = pos["open_price"].to_numpy()[ok]
    return float(((price >= lo) & (price <= hi)).sum() / len(pos))


def choose_offset(pos: pd.DataFrame, bars: pd.DataFrame) -> tuple[int | None, dict[int, float]]:
    scores = {h: alignment(pos, bars, h) for h in (SERVER_OFFSET_H, SERVER_OFFSET_H - 1, SERVER_OFFSET_H + 1)}
    if scores[SERVER_OFFSET_H] >= MATCH_MIN:
        return SERVER_OFFSET_H, scores
    best = max(scores, key=lambda h: scores[h])
    return (best if scores[best] >= MATCH_MIN else None), scores


def pf(pnl: np.ndarray) -> float:
    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf")


def max_consecutive_losses(pnl: np.ndarray) -> int:
    best = run = 0
    for x in pnl:
        run = run + 1 if x < 0 else 0
        best = max(best, run)
    return best


def max_drawdown(pnl: np.ndarray, start: float) -> tuple[float, float]:
    equity = start + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[start], equity]))[1:]
    dd = peak - equity
    i = int(dd.argmax())
    return float(dd[i]), float(dd[i] / peak[i] * 100)


def descriptive(pos: pd.DataFrame, start: float) -> dict:
    by_close = pos.sort_values("close_time")
    pnl = by_close["net"].to_numpy()
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    weekly = by_close.groupby(by_close["close_time"].dt.strftime("%G-W%V"))["net"].sum()
    monthly = by_close.groupby(by_close["close_time"].dt.strftime("%Y-%m"))["net"].sum()
    dd_usd, dd_pct = max_drawdown(pnl, start)
    sorted_pnl = np.sort(pnl)[::-1]
    net = float(pnl.sum())
    dur_min = (pos["close_time"] - pos["open_time"]).dt.total_seconds() / 60
    days = pos["open_time"].dt.date.nunique()
    return {
        "positions": len(pos),
        "net_usd": round(net, 2),
        "profit_factor": round(pf(pnl), 3),
        "win_rate": round(len(wins) / len(pnl), 3),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "expectancy": round(net / len(pnl), 2),
        "weekly": {k: round(v, 2) for k, v in weekly.items()},
        "negative_weeks": int((weekly < 0).sum()),
        "monthly": {k: round(v, 2) for k, v in monthly.items()},
        "max_consecutive_losses": max_consecutive_losses(pnl),
        "max_drawdown_usd": round(dd_usd, 2),
        "max_drawdown_pct": round(dd_pct, 2),
        "longs": int((pos["dir"] == 1).sum()),
        "longs_net": round(float(pos.loc[pos["dir"] == 1, "net"].sum()), 2),
        "shorts": int((pos["dir"] == -1).sum()),
        "shorts_net": round(float(pos.loc[pos["dir"] == -1, "net"].sum()), 2),
        "duration_min_median": round(float(dur_min.median()), 1),
        "duration_min_max": round(float(dur_min.max()), 1),
        "trading_days": days,
        "positions_per_day": round(len(pos) / days, 2),
        "top3_share_of_net": round(float(sorted_pnl[:3].sum() / net), 3) if net else None,
        "top10_share_of_net": round(float(sorted_pnl[:10].sum() / net), 3) if net else None,
        "net_without_top3": round(float(sorted_pnl[3:].sum()), 2),
        "volumes": {str(k): int(v) for k, v in pos["volume"].value_counts().items()},
    }


def mae_usd(pos: pd.DataFrame, bars: pd.DataFrame, e: np.ndarray, x: np.ndarray) -> np.ndarray:
    low, high = bars["low"].to_numpy(), bars["high"].to_numpy()
    out = np.zeros(len(pos))
    for j, (d, p, v) in enumerate(zip(pos["dir"], pos["open_price"], pos["volume"])):
        seg = slice(e[j], x[j] + 1)
        adverse = p - low[seg].min() if d == 1 else high[seg].max() - p
        out[j] = max(adverse, 0.0) * CONTRACT_OZ * v
    return out


def management_risk(pos: pd.DataFrame, bars: pd.DataFrame, e: np.ndarray, mae: np.ndarray, start: float) -> dict:
    opens = bars["open"].to_numpy()
    p = pos.reset_index(drop=True)
    hedged = averaged = 0
    for j in range(len(p)):
        t = p.at[j, "open_time"]
        live = p[(p["open_time"] < t) & (p["close_time"] > t)]
        if (live["dir"] == -p.at[j, "dir"]).any():
            hedged += 1
        same = live[live["dir"] == p.at[j, "dir"]]
        floating = same["dir"] * (opens[e[j]] - same["open_price"])
        if (floating < 0).any():
            averaged += 1
    by_open = p.sort_values("open_time").reset_index(drop=True)
    after_loss = up_after_loss = 0
    for j in range(1, len(by_open)):
        prev = by_open[by_open["close_time"] <= by_open.at[j, "open_time"]]
        if prev.empty or prev.iloc[-1]["net"] >= 0:
            continue
        after_loss += 1
        up_after_loss += int(by_open.at[j, "volume"] > prev.iloc[-1]["volume"])
    no_sl = float((p["sl"] == 0).mean())
    mae_pct_max = float((mae / start * 100).max())
    return {
        "share_without_sl": round(no_sl, 3),
        "opened_while_opposite_open": hedged,
        "added_to_losing_same_side": averaged,
        "entries_after_a_loss": after_loss,
        "lot_increased_after_loss": up_after_loss,
        "mae_usd_max": round(float(mae.max()), 2),
        "mae_usd_median": round(float(np.median(mae)), 2),
        "mae_pct_of_balance_max": round(mae_pct_max, 2),
        "high_management_risk": bool(no_sl > 0.5 or mae_pct_max > 20),
    }


def spread_cost_by_hour(bars: pd.DataFrame) -> np.ndarray:
    med = bars.groupby(bars.index.hour)["spread_points"].median()
    return np.array([med.get(h, med.median()) for h in range(24)]) * POINT


def simulate(pos: pd.DataFrame, bars: pd.DataFrame, e: np.ndarray, x: np.ndarray) -> dict:
    opens = bars["open"].to_numpy()
    hours = bars.index.hour.to_numpy()
    dates = bars.index.date
    cost_h = spread_cost_by_hour(bars)
    vol = pos["volume"].to_numpy()
    dur = x - e
    obs = pos["dir"].to_numpy() * (opens[x] - opens[e]) * CONTRACT_OZ * vol - cost_h[hours[e]] * CONTRACT_OZ * vol
    p_long = float((pos["dir"] == 1).mean())
    rng = np.random.default_rng(SEED)
    n = len(pos)

    dirs = np.where(rng.random((N_SIMS, n)) < p_long, 1, -1)
    n1 = dirs * ((opens[x] - opens[e]) * CONTRACT_OZ * vol)[None, :] - (cost_h[hours[e]] * CONTRACT_OZ * vol)[None, :]

    h_lo, h_hi = int(hours[e].min()), int(hours[e].max())
    last = len(opens) - 1
    n2 = np.empty((N_SIMS, n))
    for j in range(n):
        cand = np.flatnonzero((dates == dates[e[j]]) & (hours >= h_lo) & (hours <= h_hi))
        cand = cand[cand + dur[j] <= last]
        if cand.size == 0:
            cand = np.array([e[j]])
        starts = rng.choice(cand, size=N_SIMS)
        d2 = np.where(rng.random(N_SIMS) < p_long, 1, -1)
        n2[:, j] = d2 * (opens[starts + dur[j]] - opens[starts]) * CONTRACT_OZ * vol[j] - cost_h[hours[starts]] * CONTRACT_OZ * vol[j]
    return {
        "observed_net_our_prices": round(float(obs.sum()), 2),
        "observed_pf_our_prices": round(pf(obs), 3),
        "entry_hours_utc": [h_lo, h_hi],
        "N1_direction": null_summary(obs, n1),
        "N2_timing_and_direction": null_summary(obs, n2),
    }


def null_summary(obs: np.ndarray, sims: np.ndarray) -> dict:
    nets = sims.sum(axis=1)
    gains = np.where(sims > 0, sims, 0).sum(axis=1)
    losses = -np.where(sims < 0, sims, 0).sum(axis=1)
    pfs = np.divide(gains, losses, out=np.full_like(gains, np.inf), where=losses > 0)
    o_net, o_pf = obs.sum(), pf(obs)
    return {
        "net_p95": round(float(np.percentile(nets, 95)), 2),
        "net_median": round(float(np.median(nets)), 2),
        "net_percentile": round(float((nets < o_net).mean() * 100), 1),
        "net_p_value": round(float((1 + (nets >= o_net).sum()) / (N_SIMS + 1)), 4),
        "pf_p95": round(float(np.percentile(pfs, 95)), 3),
        "pf_percentile": round(float((pfs < o_pf).mean() * 100), 1),
        "beats_p95": bool(o_net > np.percentile(nets, 95)),
    }


def verdict(desc: dict, nulls: dict | None) -> str:
    n, net, prof = desc["positions"], desc["net_usd"], desc["profit_factor"]
    if n < 30:
        return "sin veredicto (menos de 30 posiciones de oro)"
    if nulls is None:
        return "sin veredicto (precios no alineados, solo descripción)"
    beats = [nulls["N1_direction"]["beats_p95"], nulls["N2_timing_and_direction"]["beats_p95"]]
    if net <= 0 or not any(beats):
        return "sin evidencia de ventaja"
    if all(beats) and prof > 1.3 and n >= 50 and desc["net_without_top3"] > 0:
        return "evidencia preliminar"
    if prof > 1.2 and n >= 50:
        return "indicio"
    return "sin evidencia de ventaja"


def main(report_path: str, bars_path: str) -> None:
    rep = read_report(Path(report_path))
    bars = pd.read_parquet(bars_path).set_index("time").sort_index()
    gold = rep.positions[rep.positions["symbol"].str.startswith(GOLD_PREFIX)].reset_index(drop=True)
    other = rep.positions[~rep.positions["symbol"].str.startswith(GOLD_PREFIX)]
    offset, scores = choose_offset(gold, bars)
    result: dict = {
        "adr": "0013",
        "period": [str(gold["open_time"].min()), str(gold["close_time"].max())],
        "alignment": {"chosen_offset_h": offset, "match_rate_by_offset": scores},
        "gold": descriptive(gold, rep.initial_deposit),
        "other_symbols": {
            "positions": len(other),
            "net_usd": round(float(other["net"].sum()), 2),
            "symbols": sorted(other["symbol"].unique().tolist()),
        },
    }
    nulls = None
    if offset is not None:
        e = to_bar_index(gold["open_time"], bars, offset)
        x = to_bar_index(gold["close_time"], bars, offset)
        mae = mae_usd(gold, bars, e, x)
        result["management_risk"] = management_risk(gold, bars, e, mae, rep.initial_deposit)
        nulls = simulate(gold, bars, e, x)
        result["nulls"] = nulls
    result["verdict"] = verdict(result["gold"], nulls)
    out = Path("research/reports/partner/adr0013_result.json")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
