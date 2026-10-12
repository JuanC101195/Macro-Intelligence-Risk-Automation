"""Two-leg backtest for pairs-v001 (ADR 0007 and its addendum).

Same fills, stops, financing and risk engine as `Backtest`; the pair adds:
- decisions and z/time exits only on hours where BOTH legs have a bar;
- both legs go through DefaultRiskEngine; if one is rejected neither is opened;
- if the fill bar of either leg is missing, both pending orders are cancelled;
- if one leg is stopped out, the other is closed at the open of its next bar;
- the consecutive-loss streak and the reported trades are per pair (net of both legs).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import groupby

from trading_system.backtest.engine import (
    Backtest,
    BacktestConfig,
    BacktestQuotes,
    BacktestResult,
    BrokerSide,
    ClosedTrade,
    _Pending,
    point_size,
    symbol_spec,
)
from trading_system.backtest.fills import Exit
from trading_system.broker.contracts import Bar, Tick
from trading_system.domain import Side
from trading_system.strategy.pairs import PairsStrategy
from trading_system.strategy.signals import Signal

PAIR_STOP_REASONS = ("stop_loss", "stop_loss_gap")


@dataclass
class _PairPosition:
    direction: int  # +1 long spread (buy A, sell B), -1 short spread
    entry_index: int  # common index of the fill bar
    risk_amount: float  # estimated loss if |z| goes from entry_z to stop_z


class PairBacktest(Backtest):
    def __init__(
        self,
        config: BacktestConfig,
        bars: Mapping[str, Sequence[Bar]],
        strategy: PairsStrategy,
        financing: Callable[[str, BrokerSide, datetime], float | None] | None = None,
    ) -> None:
        super().__init__(config, bars, financing=financing)
        self.strategy = strategy
        self.legs = (strategy.params.leg_a, strategy.params.leg_b)
        self.pair: _PairPosition | None = None
        self._pending_pair: _PairPosition | None = None
        self._pair_pnl = 0.0
        self._pair_risk: dict[datetime, float] = {}  # entry time -> risk_amount
        self.leg_trades: list[ClosedTrade] = []

    def run(self) -> BacktestResult:
        timeline = sorted(
            (bar.time, sym, i) for sym, bars in self.bars.items() for i, bar in enumerate(bars)
            if bar.time < self.cfg.end
        )
        for t, group in groupby(timeline, key=lambda item: item[0]):
            batch = list(group)
            present = {sym for _, sym, _ in batch}
            self._cancel_unpaired_fill(t, present)
            for _, sym, i in batch:
                self._close_orphan(sym, self.bars[sym][i])
                self._update_positions(sym, i)
            self._promote_fill(t)
            if present >= set(self.legs) and t >= self.cfg.start:
                rows = {sym: self.bars[sym][i] for _, sym, i in batch}
                self._on_common_bar(t, rows)
        self._close_all_at_end()
        self.leg_trades = list(self.trades)
        self.trades = self._merge_pairs(self.leg_trades)
        return BacktestResult(
            config=self.cfg, trades=self.trades, daily_equity=self.daily,
            hold_reasons=self.holds, rejections=self.rejections,
            cancelled_fills=self.cancelled, bars_total=self.bars_total,
            bars_in_market=self.bars_in_market, final_equity=self.book.balance,
        )

    # --- fills and exits ----------------------------------------------------------------

    def _cancel_unpaired_fill(self, t: datetime, present: set[str]) -> None:
        expected = {p.expected_open for p in self.book.pending.values()}
        if t in expected and not present >= set(self.legs):
            self.cancelled += len(self.book.pending)
            self.book.pending.clear()
            self._pending_pair = None

    def _promote_fill(self, t: datetime) -> None:
        if self._pending_pair is None:
            return
        if not all(s in self.book.open for s in self.legs):
            if not self.book.pending:  # both fills were cancelled (no bar at the open)
                self._pending_pair = None
            return
        index = self.strategy.index(t)
        assert index is not None  # both legs filled on this bar, so it is a common bar
        self._pending_pair.entry_index = index
        self.pair = self._pending_pair
        self._pending_pair = None
        self._pair_risk[t] = self.pair.risk_amount

    def _close_orphan(self, sym: str, bar: Bar) -> None:
        """The other leg was stopped out: close this one at this bar's open."""
        if self.pair is None or sym not in self.book.open:
            return
        other = self.legs[1] if sym == self.legs[0] else self.legs[0]
        if other in self.book.open:
            return
        if bar.time < self.trades[-1].exit_time:
            return  # the other leg stopped inside this same hour: no look-ahead
        side = self.book.open[sym].intent.side
        self._close(sym, Exit(self._market_exit_price(sym, side, bar.open), "pair_leg_closed"),
                    bar.time)

    def _market_exit_price(self, sym: str, side: BrokerSide, price: float) -> float:
        point = point_size(sym)
        slip = self.cfg.costs.slippage(sym) * point
        if side == "buy":  # sell at the bid
            return price - slip
        return price + self.cfg.costs.spread(sym) * point + slip  # buy back at the ask

    def _count_loss(self, pnl: float) -> None:
        self._pair_pnl += pnl
        if any(s in self.book.open for s in self.legs):
            return  # the other leg is still open: the pair result is not known yet
        super()._count_loss(self._pair_pnl)
        self._pair_pnl = 0.0
        self.pair = None

    # --- common bars --------------------------------------------------------------------

    def _on_common_bar(self, t: datetime, rows: Mapping[str, Bar]) -> None:
        close_time = t + self.tf
        self.bars_total += 1
        if self.pair is not None and all(s in self.book.open for s in self.legs):
            self.bars_in_market += 1
            if self.strategy.should_exit(t, self.pair.direction, self.pair.entry_index):
                for sym in self.legs:
                    side = self.book.open[sym].intent.side
                    price = self._market_exit_price(sym, side, rows[sym].close)
                    self._close(sym, Exit(price, "signal_exit"), close_time)
            return
        if self.pair is None and self._pending_pair is None and not self.book.open:
            self._decide_pair(t, rows, close_time)

    def _decide_pair(self, t: datetime, rows: Mapping[str, Bar], close_time: datetime) -> None:
        direction, hold = self.strategy.entry(t)
        sized = None if hold else self._size(t, rows, direction)
        if isinstance(sized, str):
            hold = sized
        if hold or not isinstance(sized, tuple):
            self.holds.update([hold or "sizing_failed"])
            return
        volumes, risk_amount = sized
        approved: list[str] = []
        for sym in self.legs:
            side = Side.LONG if (direction > 0) == (sym == self.legs[0]) else Side.SHORT
            rejection = self._approve_leg(sym, side, rows[sym], close_time, volumes[sym])
            if rejection:
                self.rejections.update(rejection)
                for s in approved:
                    self.book.pending.pop(s, None)
                return
            approved.append(sym)
        self._pending_pair = _PairPosition(direction, -1, round(risk_amount, 2))

    def _size(self, t: datetime, rows: Mapping[str, Bar], direction: int
              ) -> tuple[dict[str, tuple[float, float]], float] | str:
        """({symbol: (volume, stop distance)}, pair risk) or a hold reason (ADR 0007
        addendum, point 5: the whole pair is scaled down if a leg exceeds the limit)."""
        p = self.strategy.params
        state = self.strategy.state(t)
        assert state is not None and direction != 0
        equity = self._equity()
        notional_a = equity * p.risk_fraction / ((p.stop_z - p.entry_z) * state.spread_std)
        notionals = {self.legs[0]: notional_a, self.legs[1]: state.beta * notional_a}
        legs: dict[str, tuple[float, float]] = {}
        worst = 0.0
        for sym in self.legs:
            atr = self.strategy.atr(sym, t)
            if atr is None:
                return "indicators_not_ready"
            spec = symbol_spec(sym, rows[sym].close)
            volume = notionals[sym] / (spec.contract_size * rows[sym].close)
            distance = p.stop_atr * atr
            worst = max(worst, volume * distance / spec.tick_size * spec.tick_value)
            legs[sym] = (volume, distance)
        if worst <= 0:
            return "sizing_failed"
        scale = min(1.0, equity * self.cfg.limits.max_risk_per_trade / worst)
        out: dict[str, tuple[float, float]] = {}
        for sym, (volume, distance) in legs.items():
            spec = symbol_spec(sym, rows[sym].close)
            steps = int(volume * scale / spec.volume_step + 1e-9)
            rounded = round(steps * spec.volume_step, 2)
            if rounded < spec.volume_min:
                return "volume_below_min"
            out[sym] = (rounded, distance)
        return out, equity * p.risk_fraction * scale

    def _approve_leg(self, sym: str, side: Side, bar: Bar, close_time: datetime,
                     sized: tuple[float, float]) -> list[str]:
        volume, distance = sized
        point = point_size(sym)
        spec = symbol_spec(sym, bar.close)
        spread_pts = self.cfg.costs.spread(sym)
        tick = Tick(time=close_time + timedelta(seconds=2), bid=bar.close,
                    ask=bar.close + spread_pts * point, spread_points=round(spread_pts))
        entry = tick.ask if side is Side.LONG else tick.bid
        sign = 1 if side is Side.LONG else -1
        target_distance = self.strategy.params.target_atr / self.strategy.params.stop_atr * distance
        signal = Signal(
            signal_id=f"{self.strategy.params.version}-{sym}-{bar.time:%Y%m%d%H}",
            symbol=sym, timeframe=self.cfg.strategy.timeframe, bar_time=bar.time, side=side,
            confidence=0.5, technical_score=0, macro_regime="unknown",
            reasons=(f"pair_leg_{side.value.lower()}",), entry_ref=entry,
            stop_loss=round(entry - sign * distance, spec.digits),
            take_profit=round(max(entry + sign * target_distance, entry * 0.1), spec.digits),
            strategy_version=self.strategy.params.version,
        )
        loss_per_lot = max(0.0, -BacktestQuotes().calc_profit(
            sym, "buy" if side is Side.LONG else "sell", 1.0, entry, signal.stop_loss or entry))
        equity = self._equity()
        fraction = volume * loss_per_lot / equity * (1 + 1e-7)
        decision = self.risk.evaluate(signal, self._account(), spec, tick, self._exposure(),
                                      risk_fraction=fraction)
        if not decision.approved or decision.intent is None:
            return list(decision.rejections)
        if abs(decision.intent.volume - volume) > 1e-9:
            return ["pair_leg_volume_mismatch"]
        self.book.pending[sym] = _Pending(decision.intent, close_time, close_time)
        return []

    # --- reporting ----------------------------------------------------------------------

    def _merge_pairs(self, legs: Sequence[ClosedTrade]) -> list[ClosedTrade]:
        """One ClosedTrade per pair (ADR 0007: one operation = one complete pair)."""
        by_entry: dict[datetime, list[ClosedTrade]] = {}
        for trade in legs:
            by_entry.setdefault(trade.entry_time, []).append(trade)
        merged = []
        for entry_time, group in sorted(by_entry.items()):
            a = next((x for x in group if x.symbol == self.legs[0]), group[0])
            reasons = [x.exit_reason for x in group]
            reason = next((r for r in reasons if r in PAIR_STOP_REASONS), a.exit_reason)
            merged.append(a.model_copy(update={
                "symbol": "/".join(self.legs),
                "exit_time": max(x.exit_time for x in group),
                "risk_amount": self._pair_risk.get(entry_time, a.risk_amount),
                "pnl": round(sum(x.pnl for x in group), 2),
                "swap": round(sum(x.swap for x in group), 2),
                "exit_reason": reason,
            }))
        return merged
