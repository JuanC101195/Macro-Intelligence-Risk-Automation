"""Gate A criterion A11 (ADR 0010): the strategy's entries against random entries.

1. `ProfileRecorder` wraps the strategy's decider during the base run (results unchanged)
   and records, per symbol, the calls while flat and, for the entries that were EXECUTED,
   the LONG share and the stop / take-profit distance in ATR(14) units of the signal bar.
2. `RandomEntries` replaces the entries: while flat, it enters with the observed
   probability, a LONG with the observed share, and a (stop, TP) pair drawn from the
   observed ones scaled by the current ATR(14). Exits, risk, costs and data are unchanged.
3. `run_null` runs seeds 0..N-1 on worker processes; `summarize` compares the observed
   profit factor with the 95th percentile of the random versions.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from trading_system.backtest.engine import Backtest
from trading_system.backtest.gates import NULL_PERCENTILE
from trading_system.backtest.metrics import compute
from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.domain import Side, bracket_error
from trading_system.strategy import indicators as ind
from trading_system.strategy.signals import MarketState, Signal

ATR_PERIOD = 14
TARGET_FLOOR = 0.10  # short targets never below 10 % of the entry (ADR 0006 addendum)

AtrMap = Mapping[tuple[str, datetime], float | None]
Decider = Callable[..., Signal]


def atr_by_bar(bars: Mapping[str, Sequence[Bar]], period: int = ATR_PERIOD
               ) -> dict[tuple[str, datetime], float | None]:
    out: dict[tuple[str, datetime], float | None] = {}
    for sym, series in bars.items():
        values = ind.atr([b.high for b in series], [b.low for b in series],
                         [b.close for b in series], period)
        out.update({(sym, b.time): v for b, v in zip(series, values, strict=True)})
    return out


@dataclass
class SymbolProfile:
    flat_calls: int = 0
    longs: int = 0
    brackets: list[tuple[float, float]] = field(default_factory=list)  # (stop, TP) in ATR

    @property
    def entries(self) -> int:
        return len(self.brackets)

    @property
    def entry_probability(self) -> float:
        return self.entries / self.flat_calls if self.flat_calls else 0.0

    @property
    def long_share(self) -> float:
        return self.longs / self.entries if self.entries else 0.0


def _usable_atr(atr: AtrMap, symbol: str, bar: Bar | None) -> float | None:
    if bar is None:
        return None
    value = atr.get((symbol, bar.time))
    return value if value is not None and value > 0 else None


def _flat(state: MarketState) -> bool:
    return not state.has_open_position and not state.risk_blocked


class ProfileRecorder:
    """Pass-through decider that records the entry profile of the base run.

    Every entry signal is kept as a candidate; `profile` keeps only those that became
    trades (ADR 0010 addendum: repeated or rejected signals must not inflate p).
    """

    def __init__(self, decider: Decider, atr: AtrMap) -> None:
        self.decider = decider
        self.atr = atr
        self.flat_calls: dict[str, int] = {}
        self.candidates: dict[tuple[str, datetime], tuple[bool, float, float]] = {}

    def __call__(self, snap: Any, bar: Bar | None, tick: Tick, spec: SymbolSpec, macro: Any,
                 state: MarketState, params: Any, symbol: str) -> Signal:
        signal = self.decider(snap, bar, tick, spec, macro, state, params, symbol)
        atr = _usable_atr(self.atr, symbol, bar)
        if bar is None or atr is None or not _flat(state):
            return signal
        self.flat_calls[symbol] = self.flat_calls.get(symbol, 0) + 1
        if signal.side is not Side.HOLD and signal.entry_ref is not None \
                and signal.stop_loss is not None and signal.take_profit is not None:
            self.candidates[(symbol, bar.time)] = (
                signal.side is Side.LONG, abs(signal.entry_ref - signal.stop_loss) / atr,
                abs(signal.take_profit - signal.entry_ref) / atr)
        return signal

    def profile(self, trades: Iterable[Any], bar_length: timedelta) -> dict[str, SymbolProfile]:
        """Profile of the EXECUTED entries; a trade's signal_time is its bar's close."""
        out = {sym: SymbolProfile(flat_calls=n) for sym, n in self.flat_calls.items()}
        for trade in trades:
            found = self.candidates.get((trade.symbol, trade.signal_time - bar_length))
            if found is None:
                raise LookupError(f"trade without a recorded signal: {trade.symbol} "
                                  f"{trade.signal_time}")
            is_long, stop_k, target_k = found
            prof = out[trade.symbol]
            prof.longs += is_long
            prof.brackets.append((stop_k, target_k))
        return out


class _Stream:
    """Reproducible uniform draws in [0, 1) from (key, counter); simulation only."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.n = 0

    def random(self) -> float:
        self.n += 1
        digest = hashlib.blake2b(f"{self.key}:{self.n}".encode(), digest_size=8).digest()
        return int.from_bytes(digest, "big") / 2**64

    def choice(self, items: Sequence[tuple[float, float]]) -> tuple[float, float]:
        return items[int(self.random() * len(items))]


def _hold(signal: Signal, reason: str) -> Signal:
    if signal.side is Side.HOLD:
        return signal
    data = signal.model_dump()
    data.update(side=Side.HOLD, confidence=0.0, reasons=(), hold_reasons=(reason,),
                entry_ref=None, stop_loss=None, take_profit=None)
    return Signal(**data)


class RandomEntries:
    """Decider with random entries matching a recorded profile (ADR 0010)."""

    def __init__(self, decider: Decider, profile: Mapping[str, SymbolProfile], atr: AtrMap,
                 seed: int) -> None:
        self.decider = decider  # still called: strategies may keep per-bar state
        self.profile = profile
        self.atr = atr
        self.seed = seed
        self._rngs: dict[str, _Stream] = {}

    def _rng(self, symbol: str) -> _Stream:
        if symbol not in self._rngs:
            self._rngs[symbol] = _Stream(f"{self.seed}:{symbol}")
        return self._rngs[symbol]

    def __call__(self, snap: Any, bar: Bar | None, tick: Tick, spec: SymbolSpec, macro: Any,
                 state: MarketState, params: Any, symbol: str) -> Signal:
        signal = self.decider(snap, bar, tick, spec, macro, state, params, symbol)
        atr = _usable_atr(self.atr, symbol, bar)
        prof = self.profile.get(symbol)
        if atr is None or prof is None or not prof.entries or not _flat(state):
            return _hold(signal, "null_not_eligible")
        rng = self._rng(symbol)
        if rng.random() >= prof.entry_probability:
            return _hold(signal, "null_no_draw")
        is_long = rng.random() < prof.long_share
        stop_k, target_k = rng.choice(prof.brackets)
        return self._entry(signal, tick, spec, atr, is_long, stop_k, target_k)

    def _entry(self, signal: Signal, tick: Tick, spec: SymbolSpec, atr: float, is_long: bool,
               stop_k: float, target_k: float) -> Signal:
        sign = 1 if is_long else -1
        entry = tick.ask if is_long else tick.bid
        stop = round(entry - sign * stop_k * atr, spec.digits)
        target = entry + sign * target_k * atr
        if not is_long:
            target = max(target, entry * TARGET_FLOOR)
        target = round(target, spec.digits)
        if bracket_error(is_long, entry, stop, target):
            return _hold(signal, "null_invalid_bracket")
        data = signal.model_dump()
        data.update(side=Side.LONG if is_long else Side.SHORT, confidence=0.5,
                    reasons=("random_entry",), hold_reasons=(), entry_ref=entry,
                    stop_loss=stop, take_profit=target,
                    signal_id=f"null{self.seed}-{signal.signal_id}")
        return Signal(**data)


# --- parallel runs ---------------------------------------------------------------------

_WORKER: dict[str, Any] = {}


def _init_worker(template: Backtest, profile: Mapping[str, SymbolProfile], atr: AtrMap
                 ) -> None:
    _WORKER.update(template=template, profile=profile, atr=atr)


def _summary(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {"trades": metrics["trades"], "pf": metrics["profit_factor"],
            "expectancy": metrics["expectancy"], "dd": metrics["max_drawdown_pct"]}


def run_seed(template: Backtest, profile: Mapping[str, SymbolProfile], atr: AtrMap,
             seed: int) -> dict[str, Any]:
    """One random-entry version of an UNRUN template backtest (fresh state each time)."""
    bt = Backtest(template.cfg, template.bars, macro=template.macro,
                  decider=RandomEntries(template.decide, profile, atr, seed),
                  exit_check=template.exit_check, financing=template.financing)
    return {"seed": seed, **_summary(compute(bt.run()))}


def _worker_seed(seed: int) -> dict[str, Any]:
    return run_seed(_WORKER["template"], _WORKER["profile"], _WORKER["atr"], seed)


def run_null(template: Backtest, profile: Mapping[str, SymbolProfile], atr: AtrMap,
             seeds: Iterable[int], workers: int | None = None) -> list[dict[str, Any]]:
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                             initargs=(template, profile, atr)) as pool:
        return list(pool.map(_worker_seed, seeds))


# --- comparison --------------------------------------------------------------------------

def _num(value: float | None) -> float:
    return 0.0 if value is None else value


def percentile(sample: Sequence[float], q: float) -> float:
    """Linear interpolation between closest ranks (numpy's default)."""
    values = sorted(sample)
    pos = (len(values) - 1) * q / 100
    lo, frac = math.floor(pos), pos - math.floor(pos)
    if frac == 0:
        return values[lo]
    return values[lo] + (values[lo + 1] - values[lo]) * frac


def rank(value: float, sample: Sequence[float]) -> float:
    """Share of the sample strictly below `value`."""
    return sum(v < value for v in sample) / len(sample)


def summarize(observed: Mapping[str, Any], null: Sequence[Mapping[str, Any]],
              profile: Mapping[str, SymbolProfile]) -> dict[str, Any]:
    pfs = [_num(n["pf"]) for n in null]
    exps = [_num(n["expectancy"]) for n in null]
    obs_pf = _num(observed["profit_factor"])
    p95 = percentile(pfs, NULL_PERCENTILE)
    return {
        "runs": len(null),
        "observed": _summary(observed),
        "null_pf": {"p5": percentile(pfs, 5), "median": percentile(pfs, 50), "p95": p95},
        "rank_pf": rank(obs_pf, pfs),
        "rank_expectancy": rank(_num(observed["expectancy"]), exps),
        "p_value_pf": (1 + sum(v >= obs_pf for v in pfs)) / (len(pfs) + 1),
        "null_trades": {"min": min(n["trades"] for n in null),
                        "max": max(n["trades"] for n in null)},
        "profile": {s: {"flat_calls": p.flat_calls, "entries": p.entries,
                        "long_share": round(p.long_share, 3)}
                    for s, p in sorted(profile.items())},
        "passes": obs_pf > p95,
        "null": list(null),
    }
