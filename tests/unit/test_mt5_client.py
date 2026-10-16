from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.fixtures.fake_mt5 import FakeMt5, floor_to
from trading_system.broker.mt5_client import (
    BrokerError,
    Mt5Client,
    fx_market_open,
    infer_utc_offset,
    mask_login,
)
from trading_system.domain import Timeframe

# Wednesday mid-session, 7 minutes into an M15 bar.
NOW = datetime(2026, 10, 14, 13, 37, 12, tzinfo=UTC)


def _client(fake: FakeMt5, **kwargs: object) -> Mt5Client:
    kwargs.setdefault("utc_offset_minutes", 180)  # FakeMt5 default server is UTC+3
    return Mt5Client(fake, clock=lambda: fake.now, **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def fake() -> FakeMt5:
    return FakeMt5(now=NOW)


class TestUtcOffset:
    @pytest.mark.parametrize("hours", [-5, 0, 2, 3])
    def test_infers_whole_hour_offsets(self, hours: int) -> None:
        tick = int((NOW - timedelta(seconds=3) + timedelta(hours=hours)).timestamp())
        assert infer_utc_offset(tick, NOW) == timedelta(hours=hours)

    def test_stale_tick_is_not_trusted(self) -> None:
        tick = int((NOW - timedelta(minutes=20) + timedelta(hours=3)).timestamp())
        assert infer_utc_offset(tick, NOW) is None

    def test_implausible_offset_rejected(self) -> None:
        # A 48h-old tick looks "fresh" at offset -45h; that offset is impossible.
        tick = int((NOW - timedelta(hours=48) + timedelta(hours=3)).timestamp())
        assert infer_utc_offset(tick, NOW) is None

    def test_offset_must_be_configured(self, fake: FakeMt5) -> None:
        client = _client(fake, utc_offset_minutes=None)
        with pytest.raises(BrokerError, match=r"MT5_SERVER_UTC_OFFSET_MINUTES.*observed: 180"):
            client.closed_bars("EURUSD", Timeframe.M15, 10)

    def test_configured_offset_used_when_feed_is_stale(self, fake: FakeMt5) -> None:
        fake.tick_age = timedelta(days=2)
        bars = _client(fake).closed_bars("EURUSD", Timeframe.M15, 3)
        assert bars[-1].time == floor_to(NOW, 15) - timedelta(minutes=15)

    def test_offset_mismatch_stops_the_client(self, fake: FakeMt5) -> None:
        # Broker moved to UTC+3 (DST) but the config still says UTC+2.
        client = _client(fake, utc_offset_minutes=120)
        with pytest.raises(BrokerError, match="mismatch"):
            client.closed_bars("EURUSD", Timeframe.M15, 10)

    def test_no_cross_check_on_weekends(self) -> None:
        saturday = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
        fake = FakeMt5(now=saturday)
        client = _client(fake, utc_offset_minutes=120)  # would mismatch if checked
        assert client.probe_utc_offset_minutes("EURUSD") is None

    @pytest.mark.parametrize(
        ("when", "is_open"),
        [
            (datetime(2026, 10, 14, 3, 0, tzinfo=UTC), True),    # Wednesday
            (datetime(2026, 10, 16, 20, 59, tzinfo=UTC), True),  # Friday before close
            (datetime(2026, 10, 16, 21, 0, tzinfo=UTC), False),  # Friday close
            (datetime(2026, 10, 17, 12, 0, tzinfo=UTC), False),  # Saturday
            (datetime(2026, 10, 18, 21, 59, tzinfo=UTC), False), # Sunday before open
            (datetime(2026, 10, 18, 22, 0, tzinfo=UTC), True),   # Sunday open
        ],
    )
    def test_fx_market_open(self, when: datetime, is_open: bool) -> None:
        assert fx_market_open(when) is is_open


class TestClosedBars:
    def test_forming_bar_is_dropped_and_times_are_utc(self, fake: FakeMt5) -> None:
        bars = _client(fake).closed_bars("EURUSD", Timeframe.M15, 5)
        current_open = floor_to(NOW, 15)  # 13:30 UTC, still forming at 13:37
        assert len(bars) == 5
        assert bars[-1].time == current_open - timedelta(minutes=15)
        assert all(b.time.tzinfo is not None for b in bars)
        assert all(b.time + timedelta(minutes=15) <= NOW for b in bars)

    def test_oldest_first_and_contiguous(self, fake: FakeMt5) -> None:
        bars = _client(fake).closed_bars("USDJPY", Timeframe.M15, 20)
        deltas = {b2.time - b1.time for b1, b2 in zip(bars, bars[1:], strict=False)}
        assert deltas == {timedelta(minutes=15)}

    def test_exactly_at_close_the_bar_counts_as_closed(self) -> None:
        at_close = datetime(2026, 10, 14, 13, 45, 0, tzinfo=UTC)
        fake = FakeMt5(now=at_close)
        # Fake's forming bar is the one opening at 13:45; the 13:30 bar just closed.
        bars = _client(fake).closed_bars("EURUSD", Timeframe.M15, 1)
        assert bars[-1].time == datetime(2026, 10, 14, 13, 30, tzinfo=UTC)

    def test_rates_failure_raises(self, fake: FakeMt5) -> None:
        fake.fail.add("copy_rates_from_pos")
        client = _client(fake)
        with pytest.raises(BrokerError, match="IPC timeout"):
            client.closed_bars("EURUSD", Timeframe.M15, 5)

    def test_count_must_be_positive(self, fake: FakeMt5) -> None:
        client = _client(fake)
        with pytest.raises(ValueError):
            client.closed_bars("EURUSD", Timeframe.M15, 0)


class TestAccountAndSymbols:
    def test_login_is_masked(self, fake: FakeMt5) -> None:
        info = _client(fake).account_info()
        assert info.login_masked == "****4567"
        assert str(fake.login) not in info.model_dump_json()
        assert info.trade_mode == "demo"

    def test_real_account_is_reported_as_real(self, fake: FakeMt5) -> None:
        fake.trade_mode = 2
        assert _client(fake).account_info().trade_mode == "real"

    def test_usdjpy_spec(self, fake: FakeMt5) -> None:
        spec = _client(fake).symbol_spec("USDJPY")
        assert spec.digits == 3
        assert spec.currency_profit == "JPY"
        assert spec.tick_value == pytest.approx(0.6667, rel=1e-3)
        assert spec.trade_allowed
        assert spec.short_allowed

    def test_unknown_symbol(self, fake: FakeMt5) -> None:
        client = _client(fake)
        with pytest.raises(BrokerError, match="not available"):
            client.symbol_spec("XXXYYY")

    def test_tick_spread_in_points(self, fake: FakeMt5) -> None:
        tick = _client(fake).last_tick("EURUSD")
        assert tick.spread_points == 12
        assert tick.time == NOW - fake.tick_age

    def test_positions_mapping(self, fake: FakeMt5) -> None:
        fake.positions = [SimpleNamespace(
            ticket=1, symbol="EURUSD", type=1, volume=0.1, price_open=1.08, sl=0.0, tp=1.07,
            time=fake.server_epoch(NOW - timedelta(hours=1)), profit=-3.5, magic=777,
            comment="abcd1234abcd1234",
        )]
        [pos] = _client(fake).positions("EURUSD")
        assert pos.side == "sell"
        assert pos.stop_loss is None
        assert pos.open_time == NOW - timedelta(hours=1)

    def test_calc_profit_and_margin(self, fake: FakeMt5) -> None:
        client = _client(fake)
        loss = client.calc_profit("USDJPY", "buy", 0.12, 150.0, 149.7)
        # docs/risk-policy.md example: ~24 USD; exact value is converted at the close price.
        assert loss == pytest.approx(-24.05, rel=1e-3)
        assert client.calc_margin("EURUSD", "buy", 0.1, 1.08) > 0
        fake.fail.add("order_calc_margin")
        with pytest.raises(BrokerError):
            client.calc_margin("EURUSD", "buy", 0.1, 1.08)


class TestConnection:
    def test_connect_passes_credentials(self, fake: FakeMt5) -> None:
        _client(fake, login="51234567", password="pw", server="MetaQuotes-Demo").connect()
        assert fake.init_kwargs is not None
        assert fake.init_kwargs["login"] == 51234567
        assert fake.init_kwargs["server"] == "MetaQuotes-Demo"

    def test_non_numeric_login_rejected(self, fake: FakeMt5) -> None:
        client = _client(fake, login="abc")
        with pytest.raises(BrokerError, match="numeric"):
            client.connect()

    def test_connect_failure_does_not_leak_password(self, fake: FakeMt5) -> None:
        fake.fail.add("initialize")
        client = _client(fake, login="51234567", password="topsecret-pw")
        with pytest.raises(BrokerError) as exc:
            client.connect()
        assert "topsecret-pw" not in str(exc.value)
        assert "51234567" not in str(exc.value)

    def test_is_connected(self, fake: FakeMt5) -> None:
        client = _client(fake)
        assert client.is_connected()
        client.shutdown()
        assert not client.is_connected()


def test_mask_login() -> None:
    assert mask_login("51234567") == "****4567"
    assert mask_login("123") == "****"


def test_client_has_no_order_methods() -> None:
    # ADR 0024: the only order-related method hands the terminal to the demo executor.
    public = {name for name in dir(Mt5Client) if not name.startswith("_")}
    order_like = {n for n in public if "order" in n and n not in {"calc_margin", "calc_profit"}}
    assert order_like == {"order_terminal"}
    assert "send" not in " ".join(public)


@pytest.mark.parametrize("trade_mode", [1, 2])  # contest, real
def test_order_terminal_refuses_non_demo_accounts(trade_mode: int) -> None:
    fake = FakeMt5(now=NOW, trade_mode=trade_mode)
    client = Mt5Client(fake, utc_offset_minutes=180, clock=lambda: NOW)
    with pytest.raises(BrokerError, match="DEMO"):
        client.order_terminal()


def test_order_terminal_on_demo_returns_the_terminal() -> None:
    fake = FakeMt5(now=NOW)
    assert Mt5Client(fake, utc_offset_minutes=180, clock=lambda: NOW).order_terminal() is fake


def test_deals_are_converted_to_utc_and_filtered() -> None:
    fake = FakeMt5(now=NOW)
    epoch = fake.server_epoch(NOW)
    trade = SimpleNamespace(ticket=10, order=5, position_id=5, symbol="EURUSD", type=0, entry=0,
                            volume=0.01, price=1.08, time=epoch, commission=-0.1, swap=0.0,
                            profit=0.0, magic=260_016, comment="abc")
    balance = SimpleNamespace(**{**vars(trade), "ticket": 11, "type": 2})
    seen: list[tuple[int, int]] = []

    def history_deals_get(date_from: int, date_to: int) -> tuple[SimpleNamespace, ...]:
        seen.append((date_from, date_to))
        return (trade, balance)

    fake.history_deals_get = history_deals_get  # type: ignore[attr-defined]
    client = Mt5Client(fake, utc_offset_minutes=180, clock=lambda: NOW)
    deals = client.deals(NOW - timedelta(days=1), NOW)
    assert [d.ticket for d in deals] == [10]
    assert deals[0].time == NOW
    assert deals[0].entry == "in"
    assert seen[0][1] == epoch  # server wall-clock epoch, not PC local time
    naive_start, naive_end = datetime(2026, 1, 1), datetime(2026, 1, 2)
    with pytest.raises(ValueError, match="timezone-aware"):
        client.deals(naive_start, naive_end)
