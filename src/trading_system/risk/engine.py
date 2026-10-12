"""DefaultRiskEngine: the ONLY component that builds OrderIntent (docs/architecture.md §5.6).

Pipeline (every rejection is reported; the first failing group stops the pipeline):
1. Gate      : breaker closed, trade signal, demo account, symbol tradeable, spread,
               open positions/trades/consecutive losses, current daily loss.
2. Prices    : entry from the live tick (ask for LONG, bid for SHORT), stop/target from
               the signal; bracket still valid, entry did not drift, stop not too close.
3. Size      : position_sizing (round down, reject below minimum).
4. Portfolio : worst-case daily loss, same-direction currency exposure.
5. Broker    : margin (MT5 order_calc_margin) and loss-at-stop cross-check (order_calc_profit).
Daily-loss, consecutive-loss and unsafe-state findings also trip the circuit breaker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trading_system.broker.contracts import AccountInfo, SymbolSpec, Tick
from trading_system.domain import Side, bracket_error
from trading_system.execution.order_intent import IntentMode, OrderIntent, make_intent_id
from trading_system.risk.contracts import CircuitBreaker, ExposureSnapshot, RiskDecision, RiskLimits
from trading_system.risk.exposure import ProfitCalculator, currency_legs, risk_to_stop
from trading_system.risk.position_sizing import SizingResult, size_position
from trading_system.strategy.signals import Signal

BrokerSide = Literal["buy", "sell"]


@dataclass(frozen=True)
class RiskConfig:
    max_entry_drift: float = 0.5  # real stop distance within +/-50% of the signal's
    max_margin_usage: float = 0.5  # of free margin
    profit_check_tolerance: float = 0.02  # |calc_profit - expected loss| / expected
    currency_exposure_mult: float = 1.0  # x max_risk_per_trade x equity, per currency


@dataclass(frozen=True)
class _Order:
    side: BrokerSide
    entry: float
    stop: float
    target: float


class DefaultRiskEngine:
    def __init__(
        self,
        limits: RiskLimits,
        breaker: CircuitBreaker,
        quotes: ProfitCalculator,
        mode: IntentMode,
        config: RiskConfig | None = None,
    ) -> None:
        self._limits = limits
        self._breaker = breaker
        self._quotes = quotes
        self._mode: IntentMode = mode
        self._cfg = config or RiskConfig()

    def evaluate(
        self,
        signal: Signal,
        account: AccountInfo,
        spec: SymbolSpec,
        tick: Tick,
        exposure: ExposureSnapshot,
    ) -> RiskDecision:
        rejections = self._gate(signal, account, spec, tick, exposure)
        if rejections:
            return _reject(rejections)

        order = self._order(signal, tick)
        rejections = self._price_checks(signal, order, spec)
        if rejections:
            return _reject(rejections)

        sizing = size_position(account.equity, self._limits.max_risk_per_trade,
                               order.entry, order.stop, spec)
        if sizing.volume is None:
            return _reject([sizing.rejection or "sizing_failed"])

        rejections = self._portfolio_checks(order, spec, account, exposure, sizing)
        rejections += self._broker_checks(order, spec, account, sizing)
        if rejections:
            return _reject(rejections)

        intent = OrderIntent(
            intent_id=make_intent_id(signal.strategy_version, signal.symbol, signal.timeframe,
                                     signal.bar_time, signal.side),
            signal_id=signal.signal_id,
            signal_bar_time=signal.bar_time,
            symbol=signal.symbol,
            side=order.side,
            entry_price=order.entry,
            stop_loss=order.stop,
            take_profit=order.target,
            volume=sizing.volume,
            risk_amount=round(sizing.risk_money_real, 2),
            strategy_version=signal.strategy_version,
            model_version=signal.model_version,
            mode=self._mode,
            reason=(",".join(signal.reasons) or signal.strategy_version)[:300],
        )
        return RiskDecision(approved=True, intent=intent,
                            risk_percent=round(sizing.risk_money_real / account.equity, 6))

    # --- 1. gate ----------------------------------------------------------------------

    def _gate(self, signal: Signal, account: AccountInfo, spec: SymbolSpec, tick: Tick,
              exposure: ExposureSnapshot) -> list[str]:
        lim = self._limits
        self._trip_on_unsafe_state(account, exposure)
        same_symbol = [p for p in exposure.open_positions if p.symbol == signal.symbol]
        rules = [
            (self._breaker.is_open(), "circuit_breaker_open"),
            (signal.side is Side.HOLD, "not_a_trade_signal"),
            (signal.symbol != spec.symbol, "symbol_mismatch"),
            (account.trade_mode != "demo", "account_not_demo"),
            (not spec.trade_allowed, "symbol_not_tradeable"),
            (signal.side is Side.SHORT and not spec.short_allowed, "short_not_allowed"),
            (tick.spread_points > lim.max_spread_points, "spread_too_wide"),
            (len(exposure.open_positions) >= lim.max_open_positions, "max_open_positions"),
            (len(same_symbol) >= lim.max_symbol_exposure, "max_symbol_exposure"),
            (exposure.trades_today >= lim.max_trades_per_day, "max_trades_per_day"),
            (exposure.consecutive_losses >= lim.max_consecutive_losses, "max_consecutive_losses"),
            (self._current_daily_loss(exposure) >= self._daily_budget(exposure),
             "daily_loss_limit"),
        ]
        return [name for violated, name in rules if violated]

    def _trip_on_unsafe_state(self, account: AccountInfo, exposure: ExposureSnapshot) -> None:
        lim = self._limits
        if account.trade_mode != "demo":
            self._breaker.trip("account_not_demo", source="risk")
        if self._current_daily_loss(exposure) >= self._daily_budget(exposure):
            self._breaker.trip("daily_loss_limit", source="risk")
        if exposure.consecutive_losses >= lim.max_consecutive_losses:
            self._breaker.trip("max_consecutive_losses", source="risk")
        if any(p.stop_loss is None for p in exposure.open_positions):
            self._breaker.trip("open_position_without_stop", source="risk")

    def _daily_budget(self, exposure: ExposureSnapshot) -> float:
        return self._limits.max_daily_loss * exposure.day_start_equity

    @staticmethod
    def _current_daily_loss(exposure: ExposureSnapshot) -> float:
        return max(0.0, -(exposure.realized_pnl_today + exposure.unrealized_pnl))

    # --- 2. prices --------------------------------------------------------------------

    @staticmethod
    def _order(signal: Signal, tick: Tick) -> _Order:
        assert signal.stop_loss is not None and signal.take_profit is not None  # Signal enforces
        if signal.side is Side.LONG:
            return _Order("buy", tick.ask, signal.stop_loss, signal.take_profit)
        return _Order("sell", tick.bid, signal.stop_loss, signal.take_profit)

    def _price_checks(self, signal: Signal, order: _Order, spec: SymbolSpec) -> list[str]:
        if bracket_error(order.side == "buy", order.entry, order.stop, order.target):
            return ["price_beyond_stop_or_target"]
        assert signal.entry_ref is not None and signal.stop_loss is not None
        planned = abs(signal.entry_ref - signal.stop_loss)
        actual = abs(order.entry - order.stop)
        drift = self._cfg.max_entry_drift
        problems = []
        if not (1 - drift) * planned <= actual <= (1 + drift) * planned:
            problems.append("entry_drifted")
        if actual < spec.stops_level_points * spec.point:
            problems.append("stop_too_close")
        return problems

    # --- 4. portfolio -----------------------------------------------------------------

    def _portfolio_checks(self, order: _Order, spec: SymbolSpec, account: AccountInfo,
                          exposure: ExposureSnapshot, sizing: SizingResult) -> list[str]:
        open_risks = [risk_to_stop(p, self._quotes) for p in exposure.open_positions]
        if any(r is None for r in open_risks):
            return ["open_position_without_stop"]
        realized_loss = max(0.0, -exposure.realized_pnl_today)
        worst_case = realized_loss + sum(r for r in open_risks if r) + sizing.risk_money_real
        problems = []
        if worst_case > self._daily_budget(exposure) + 1e-9:
            problems.append("daily_loss_budget")

        cap = (self._cfg.currency_exposure_mult * self._limits.max_risk_per_trade
               * account.equity)
        totals: dict[str, float] = {}
        for pos, risk in zip(exposure.open_positions, open_risks, strict=True):
            for ccy, sign in currency_legs(pos.symbol, pos.side).items():
                totals[ccy] = totals.get(ccy, 0.0) + sign * (risk or 0.0)
        for ccy, sign in currency_legs(spec.symbol, order.side).items():
            existing = totals.get(ccy, 0.0)
            if existing * sign > 0 and abs(existing + sign * sizing.risk_money_real) > cap + 1e-9:
                problems.append(f"currency_exposure_{ccy}")
        return problems

    # --- 5. broker --------------------------------------------------------------------

    def _broker_checks(self, order: _Order, spec: SymbolSpec, account: AccountInfo,
                       sizing: SizingResult) -> list[str]:
        assert sizing.volume is not None
        problems = []
        margin = self._quotes.calc_margin(spec.symbol, order.side, sizing.volume, order.entry)
        if margin > self._cfg.max_margin_usage * account.margin_free:
            problems.append("insufficient_margin")
        pnl = self._quotes.calc_profit(spec.symbol, order.side, sizing.volume,
                                       order.entry, order.stop)
        expected = -sizing.risk_money_real
        if abs(pnl - expected) > self._cfg.profit_check_tolerance * sizing.risk_money_real:
            problems.append("tick_value_mismatch")
        return problems


def _reject(rejections: list[str]) -> RiskDecision:
    return RiskDecision(approved=False, rejections=tuple(dict.fromkeys(rejections)))
