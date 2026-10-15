r"""B1' (part 1) of ADR 0017: replay the last 12 months of real H4 bars through PaperTrader.

Bar by bar, as if live: the tick is the next bar's open (+30 points ask) and trading resumes
at the next bar's open (so closes into a break or a weekend wait for the reopen). A new
process (store + trader) every RESTART_EVERY bars tests restarts. Checks: no errors, no
duplicates, parity `ok`. Read-only. Run from the main checkout (needs .env):
    $env:PYTHONPATH='<checkout>\src'; .\.venv\Scripts\python.exe <this file>
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from trading_system.backtest.engine import symbol_spec
from trading_system.broker.contracts import Bar, SymbolSpec, Tick
from trading_system.broker.mt5_client import Mt5Client
from trading_system.config import load_settings
from trading_system.domain import Timeframe
from trading_system.storage.paper_store import PaperStore
from trading_system.workers import paper_report
from trading_system.workers.paper_loop import PaperConfig, PaperTrader, frozen_params

SYMBOL = "XAUUSD"
H4 = timedelta(hours=4)
RESTART_EVERY = 50
OUT = Path("research/reports")


class ReplayMarket:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.k = 0

    def resume(self) -> datetime:
        return self.bars[self.k].time  # next bar open = trading resumed after the close

    def now(self) -> datetime:
        return self.resume() + timedelta(minutes=1)

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        return symbol_spec(symbol, self.bars[self.k - 1].close)

    def closed_bars(self, symbol: str, tf: Timeframe, count: int) -> list[Bar]:
        if tf is Timeframe.M1:
            price = self.bars[self.k].open
            return [Bar(time=self.resume(), open=price, high=price, low=price, close=price,
                        tick_volume=1, spread_points=30)]
        return self.bars[:self.k][-count:]

    def last_tick(self, symbol: str) -> Tick:
        bid = self.bars[self.k].open
        return Tick(time=self.now(), bid=bid, ask=round(bid + 0.30, 2), spread_points=30)


def main() -> int:
    cfg, params = PaperConfig(), frozen_params()
    client = Mt5Client.from_settings(load_settings())
    client.connect()
    bars = client.closed_bars(SYMBOL, Timeframe.H4, cfg.history_bars + 1_700)
    client.shutdown()
    since = datetime.now(UTC) - timedelta(days=365)
    first = next(i for i, b in enumerate(bars) if b.time >= since)
    OUT.mkdir(parents=True, exist_ok=True)
    db = OUT / "paper_replay.db"
    db.unlink(missing_ok=True)
    market = ReplayMarket(bars)
    statuses: Counter[str] = Counter()
    store, trader = None, None
    for n, k in enumerate(range(first, len(bars))):
        if n % RESTART_EVERY == 0:  # a new process
            if store is not None:
                store.close()
            store = PaperStore(db)
            trader = PaperTrader(market, store, clock=market.now)
        market.k = k
        statuses[trader.tick().status] += 1  # type: ignore[union-attr]
    assert store is not None
    trades = store.trades()
    intents = Counter(t.intent.intent_id for t in trades)
    result = {
        "period": f"{bars[first].time:%Y-%m-%d} .. {bars[-2].time:%Y-%m-%d}",
        "bars": len(bars) - first, "restarts": (len(bars) - first) // RESTART_EVERY,
        "statuses": dict(statuses), "duplicates": sum(c > 1 for c in intents.values()),
        "summary": paper_report.summary(store),
        "parity": paper_report.parity(store, bars[:-1], params, cfg.capital),
    }
    (OUT / "paper_replay.json").write_text(json.dumps(result, indent=2, default=str),
                                           encoding="utf-8")
    parity = result["parity"]
    print(json.dumps({k: v for k, v in result.items() if k != "parity"}, indent=2, default=str))
    print("parity:", parity["status"], "unexplained:", parity.get("unexplained"),
          "rows:", len(parity.get("trades", [])))
    for row in parity.get("trades", []):
        print(" ", row["signal_bar"], "engine", row["engine"], "\n    paper ", row["paper"])
    return 0 if parity["status"] == "ok" and not result["duplicates"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
