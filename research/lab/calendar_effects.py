"""ADR 0022: oro noche/día (XAUUSD M1) y cambio de mes (US500 + US30 D1).

Uso, desde el checkout principal y con el entorno de laboratorio:

    .venv-research\\Scripts\\python.exe research\\lab\\calendar_effects.py [--nulls 200]

Reutiliza la Puerta A A1–A9 de orb_us.py. Escribe research/reports/calendar_effects_result.json.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from orb_us import gate, pf, weekly  # noqa: E402

NY = "America/New_York"
RISK = 0.0025
GOLD_MIN_SPREAD, GOLD_SLIP = 0.30, 0.05
IDX_COST = {"US500": (0.50, 0.20), "US30": (2.00, 1.00)}  # (spread, deslizamiento por lado)
MARKUP = 1.0
DAY_OPEN, DAY_CLOSE = 8 * 60 + 20, 13 * 60 + 30
TOM_END = pd.Timestamp("2025-10-01")


def usd_rate(rates: list[list], when: pd.Timestamp) -> float:
    keys = [pd.Timestamp(d) for d, _ in rates]
    i = max(np.searchsorted(keys, when.tz_localize(None).normalize(), side="right") - 1, 0)
    return float(rates[i][1])


def financing(rates: list[list], entry_t: pd.Timestamp, exit_t: pd.Timestamp, price: float,
              cm: float) -> float:
    nights = (exit_t.normalize() - entry_t.normalize()).days
    return nights * (max(usd_rate(rates, entry_t), 0.0) + MARKUP) / 100 / 360 * price * cm


# ---------------------------------------------------------------------- oro
class Gold:
    def __init__(self) -> None:
        files = sorted(glob.glob("research/datasets/XAUUSD_M1_20[0-2][0-9]0101_*.parquet"))
        files += glob.glob("research/datasets/XAUUSD_M1_20260922_*.parquet")
        df = pd.concat(pd.read_parquet(f) for f in files).drop_duplicates("time").sort_values("time")
        df = df[df["time"] < pd.Timestamp("2026-10-16", tz="UTC")].reset_index(drop=True)
        ny = df["time"].dt.tz_convert(NY)
        self.t = ny
        self.tns = df["time"].dt.as_unit("ns").astype("int64").to_numpy()
        self.o, self.h, self.l = (df[c].to_numpy() for c in ("open", "high", "low"))
        self.spr = np.maximum(df["spread_points"].to_numpy() * 0.01, GOLD_MIN_SPREAD)
        self.mins = (ny.dt.hour * 60 + ny.dt.minute).to_numpy()
        self.date = ny.dt.normalize()
        daily = df.assign(d=self.date).groupby("d").agg(h=("high", "max"), l=("low", "min"),
                                                         c=("close", "last"))
        prev_c = daily["c"].shift(1)
        tr = np.maximum(daily["h"] - daily["l"],
                        np.maximum((daily["h"] - prev_c).abs(), (daily["l"] - prev_c).abs()))
        self.atr = tr.rolling(14).mean().shift(1)  # solo días previos
        self.days = list(daily.index)
        starts = np.flatnonzero(np.r_[True, self.date.to_numpy()[1:] != self.date.to_numpy()[:-1]])
        self.bounds = {d: (int(a), int(b)) for d, a, b in
                       zip(self.days, starts, np.r_[starts[1:], len(df)])}

    def bar_at(self, day: pd.Timestamp, minute: int) -> int | None:
        """Primera vela del día en o después del minuto dado (máx. 10 min de tolerancia)."""
        a, b = self.bounds[day]
        seg = np.flatnonzero((self.mins[a:b] >= minute) & (self.mins[a:b] < minute + 10))
        return a + int(seg[0]) if seg.size else None


def gold_trade(g: Gold, i: int, j: int, side: int, atr: float, rates: list, cm: float
               ) -> tuple[float, float] | None:
    slip = GOLD_SLIP * cm
    entry = g.o[i] + g.spr[i] * cm + slip if side == 1 else g.o[i] - slip
    stop = entry - side * 2 * atr
    seg = slice(i, j)
    if side == 1:
        hit = np.flatnonzero(g.l[seg] <= stop)
    else:
        hit = np.flatnonzero(g.h[seg] + g.spr[seg] * cm >= stop)
    if hit.size:
        k = i + int(hit[0])
        gap = g.o[k] if side == 1 else g.o[k] + g.spr[k] * cm
        px = (min(stop, gap) - slip) if side == 1 else (max(stop, gap) + slip)
        out_t = g.t.iloc[k]
    else:
        px = g.o[j] - slip if side == 1 else g.o[j] + g.spr[j] * cm + slip
        out_t = g.t.iloc[j]
    pnl = side * (px - entry)
    if side == 1:
        pnl -= financing(rates, g.t.iloc[i], out_t, entry, cm)
    return pnl / (2 * atr), pnl


def gold_run(g: Gold, kind: str, rates: list, shift: int = 0, cm: float = 1.0) -> pd.DataFrame:
    rows = []
    d_open, d_close = DAY_OPEN + shift, DAY_CLOSE + shift
    for n, day in enumerate(g.days[:-1]):
        atr = g.atr.get(day, np.nan)
        if np.isnan(atr) or day.weekday() >= 5:
            continue
        if kind == "night":
            i = g.bar_at(day, d_close)
            nxt = next((d for d in g.days[n + 1:n + 5] if d.weekday() < 5), None)
            j = g.bar_at(nxt, d_open) if nxt is not None else None
            side = 1
        else:
            i, j, side = g.bar_at(day, d_open), g.bar_at(day, d_close), -1
        if i is None or j is None or j <= i:
            continue
        r, _ = gold_trade(g, i, j, side, atr, rates, cm)
        rows.append(("XAUUSD", day.tz_localize(None), side, r, RISK, r * RISK))
    return pd.DataFrame(rows, columns=["symbol", "date", "side", "r", "risk", "ret"])


# ---------------------------------------------------------------------- TOM
def load_d1(symbol: str) -> pd.DataFrame:
    f = sorted(glob.glob(f"research/datasets/{symbol}_D1_2004*.parquet"))[0]
    df = pd.read_parquet(f).sort_values("time").reset_index(drop=True)
    # Las velas D1 vienen etiquetadas a las 21:00 UTC del día anterior (medianoche del
    # servidor, UTC+3); la fecha de sesión es la del servidor (adenda 2 de la ADR 0022).
    df["date"] = (df["time"] + pd.Timedelta(hours=3)).dt.tz_convert(None).dt.normalize()
    prev_c = df["close"].shift(1)
    tr = np.maximum(df["high"] - df["low"],
                    np.maximum((df["high"] - prev_c).abs(), (df["low"] - prev_c).abs()))
    df["atr"] = tr.rolling(14).mean().shift(1)
    df["ym"] = df["date"].dt.to_period("M")
    df["dom"] = df.groupby("ym").cumcount()  # 0 = primer día hábil
    df["dom_rev"] = df.groupby("ym").cumcount(ascending=False)  # 0 = último
    return df[df["date"] < TOM_END].reset_index(drop=True)


def tom_trade(df: pd.DataFrame, i: int, j: int, symbol: str, rates: list, cm: float) -> float:
    spread, slip = (c * cm for c in IDX_COST[symbol])
    entry = df.at[i, "close"] + spread + slip
    atr = df.at[i, "atr"]
    stop = entry - 2 * atr
    px = df.at[j, "close"] - slip
    exit_t = df.at[j, "date"]
    for k in range(i + 1, j + 1):
        if df.at[k, "low"] <= stop:
            px = min(stop, df.at[k, "open"]) - slip
            exit_t = df.at[k, "date"]
            break
    pnl = px - entry - financing(rates, pd.Timestamp(df.at[i, "date"], tz=NY),
                                 pd.Timestamp(exit_t, tz=NY), entry, cm)
    return pnl / (2 * atr)


def tom_run(data: dict[str, pd.DataFrame], rates: list, entry_rev: int = 1, exit_dom: int = 2,
            cm: float = 1.0, random_offsets: dict | None = None) -> pd.DataFrame:
    """entry_rev: 1 = penúltimo día hábil; exit_dom: 2 = tercer día hábil del mes siguiente."""
    rows = []
    for symbol, df in data.items():
        entries = df.index[df["dom_rev"] == entry_rev]
        for i in entries:
            if np.isnan(df.at[i, "atr"]):
                continue
            nxt = df.index[(df["ym"] == df.at[i, "ym"] + 1) & (df["dom"] == exit_dom)]
            if not len(nxt):
                continue
            j = int(nxt[0])
            if random_offsets is not None:
                hold = j - i
                start = random_offsets[(symbol, i)]
                i, j = start, start + hold
                if j >= len(df) or np.isnan(df.at[i, "atr"]):
                    continue
            r = tom_trade(df, i, j, symbol, rates, cm)
            rows.append((symbol, df.at[i, "date"], 1, r, RISK, r * RISK))
    return pd.DataFrame(rows, columns=["symbol", "date", "side", "r", "risk", "ret"]).sort_values("date")


def tom_null(data: dict[str, pd.DataFrame], rates: list, base_keys: list, runs: int) -> list[float]:
    out = []
    for seed in range(runs):
        rng = np.random.default_rng(seed)
        offsets = {}
        for symbol, i in base_keys:
            df = data[symbol]
            same_month = df.index[df["ym"] == df.at[i, "ym"]]
            offsets[(symbol, i)] = int(rng.choice(same_month))
        out.append(pf(tom_run(data, rates, random_offsets=offsets)["ret"].to_numpy()))
    return out


def gold_audit(g: Gold, rates: list, n: int = 20) -> dict:
    """Recalcula operaciones de noche vela a vela, sin flatnonzero."""
    rng = np.random.default_rng(7)
    checked = mismatches = 0
    for day in rng.permutation(g.days[20:-5]):
        atr = g.atr.get(day, np.nan)
        pos = g.days.index(day)
        nxt = next((d for d in g.days[pos + 1:pos + 5] if d.weekday() < 5), None)
        if np.isnan(atr) or day.weekday() >= 5 or nxt is None:
            continue
        i, j = g.bar_at(day, DAY_CLOSE), g.bar_at(nxt, DAY_OPEN)
        if i is None or j is None:
            continue
        entry = g.o[i] + g.spr[i] + GOLD_SLIP
        stop, px, out_t = entry - 2 * atr, g.o[j] - GOLD_SLIP, g.t.iloc[j]
        for k in range(i, j):
            if g.l[k] <= stop:
                px, out_t = min(stop, g.o[k]) - GOLD_SLIP, g.t.iloc[k]
                break
        naive = (px - entry - financing(rates, g.t.iloc[i], out_t, entry, 1.0)) / (2 * atr)
        fast, _ = gold_trade(g, i, j, 1, atr, rates, 1.0)
        checked += 1
        mismatches += abs(naive - fast) > 1e-9
        if checked == n:
            break
    return {"checked": checked, "mismatches": int(mismatches)}


# --------------------------------------------------------------------- main
def evaluate(base: pd.DataFrame, c15: pd.DataFrame, c2: pd.DataFrame, nbs: dict) -> dict:
    base, c15, c2 = (x.sort_values("date").reset_index(drop=True) for x in (base, c15, c2))
    first, last = base["date"].min(), base["date"].max()
    g = gate(base, c15, c2, nbs, first, last)
    g["weekly"] = weekly(base)
    return g


def split(base: pd.DataFrame, year: int) -> dict:
    a, b = base[base["date"].dt.year < year], base[base["date"].dt.year >= year]
    return {f"before_{year}_pf": round(pf(a["ret"].to_numpy()), 3),
            f"from_{year}_pf": round(pf(b["ret"].to_numpy()), 3), f"from_{year}_trades": len(b)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nulls", type=int, default=200)
    args = ap.parse_args()
    rates = json.load(open("research/datasets/fred_rates.json", encoding="utf-8"))["USD"]
    result: dict = {"adr": "0022"}

    g = Gold()
    result["gold_audit"] = gold_audit(g, rates)
    for kind, name in (("night", "gold-night-long"), ("day", "gold-day-short")):
        base = gold_run(g, kind, rates)
        nbs = {f"shift={s:+d}min": gold_run(g, kind, rates, shift=s) for s in (-60, 60)}
        res = evaluate(base, gold_run(g, kind, rates, cm=1.5), gold_run(g, kind, rates, cm=2.0), nbs)
        res["publication_split"] = split(base, 2018)
        res["A11"] = "solo si A1–A9 pasan" if not res["A1_to_A9_pass"] else "pendiente (correr aparte)"
        result[name] = res
        print(name, json.dumps(res["summary"], default=str)[:400], flush=True)

    data = {s: load_d1(s) for s in IDX_COST}
    base = tom_run(data, rates)
    nbs = {"entry=-3": tom_run(data, rates, entry_rev=2), "entry=-1": tom_run(data, rates, entry_rev=0),
           "exit=+2": tom_run(data, rates, exit_dom=1), "exit=+4": tom_run(data, rates, exit_dom=3)}
    res = evaluate(base, tom_run(data, rates, cm=1.5), tom_run(data, rates, cm=2.0), nbs)
    res["publication_split"] = split(base, 2012)
    if args.nulls and res["A1_to_A9_pass"]:
        keys = [(s, int(df.index[df["date"] == d][0])) for s, d in zip(base["symbol"], base["date"])
                for df in [data[s]]]
        pfs = tom_null(data, rates, keys, args.nulls)
        obs = pf(base["ret"].to_numpy())
        res["A11"] = {"null_pf_p95": round(float(np.percentile(pfs, 95)), 3), "observed_pf": round(obs, 3),
                      "beats_p95": bool(obs > np.percentile(pfs, 95))}
    else:
        res["A11"] = "no corrido (A1–A9 no pasan)"
    result["tom-v1"] = res
    out = Path("research/reports/calendar_effects_result.json")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
