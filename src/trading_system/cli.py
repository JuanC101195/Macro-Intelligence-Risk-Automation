"""Command line entry point: `trading-system ...`."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

from trading_system import __version__
from trading_system.backtest.gates import NULL_RUNS
from trading_system.broker import history
from trading_system.broker.mt5_client import BrokerError, Mt5Client
from trading_system.config import ConfigurationError, Settings, load_settings
from trading_system.domain import Timeframe
from trading_system.macro import recorder
from trading_system.macro.crucix_client import CrucixClient

DATASETS = Path("research/datasets")
REPORTS = Path("research/reports")
NullRuns = Annotated[int, typer.Option(
    help="Random-entry versions for A11 (ADR 0010: 200); 0 leaves A11 pending")]
EXPERIMENTS = Path("research/experiments.jsonl")
RATES_FILE = "fred_rates.json"

app = typer.Typer(help="Intelligence Trading Platform", no_args_is_help=True)
config_app = typer.Typer(help="Configuration commands", no_args_is_help=True)
mt5_app = typer.Typer(help="MetaTrader 5 (read-only)", no_args_is_help=True)
data_app = typer.Typer(help="Historical data", no_args_is_help=True)
macro_app = typer.Typer(help="Crucix macro context", no_args_is_help=True)
backtest_app = typer.Typer(help="Backtests and ADR 0002 gates", no_args_is_help=True)
paper_app = typer.Typer(help="Paper trading, no orders sent (ADR 0016)", no_args_is_help=True)
demo_app = typer.Typer(help="Demo account executor (ADR 0024)", no_args_is_help=True)
PAPER_DB = Path("data/paper/paper.db")
app.add_typer(backtest_app, name="backtest")
app.add_typer(paper_app, name="paper")
app.add_typer(demo_app, name="demo")
app.add_typer(config_app, name="config")
app.add_typer(mt5_app, name="mt5")
app.add_typer(data_app, name="data")
app.add_typer(macro_app, name="macro")


def _crucix(settings: Settings) -> CrucixClient:
    if not settings.crucix_enabled:
        typer.echo("Crucix is disabled (CRUCIX_ENABLED=false)", err=True)
        raise typer.Exit(code=1)
    return CrucixClient(
        settings.crucix_base_url,
        max_age=timedelta(minutes=settings.macro_max_age_minutes),
    )


def _settings_or_exit() -> Settings:
    try:
        return load_settings()
    except ConfigurationError as exc:
        typer.echo(f"INVALID: {exc}", err=True)
        raise typer.Exit(code=1) from None


def _connected_client(settings: Settings) -> Mt5Client:
    client = Mt5Client.from_settings(settings)
    try:
        client.connect()
    except BrokerError as exc:
        typer.echo(f"MT5 ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    return client


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@config_app.command("check")
def config_check() -> None:
    """Validate the current configuration (.env + environment). Exit 1 if unsafe."""
    settings = _settings_or_exit()
    typer.echo("OK")
    typer.echo(json.dumps(settings.public_summary(), indent=2))


@demo_app.command("check")
def demo_check(
    symbol: Annotated[str, typer.Option(help="Symbol the demo will trade")] = "XAUUSD",
) -> None:
    """Show whether demo orders would be allowed and how they would be sent. Sends NOTHING.

    Exit 0 if every guard passes, 3 if demo orders are not allowed yet.
    """
    from trading_system.execution import demo_executor as dx

    settings = _settings_or_exit()
    client = _connected_client(settings)
    try:
        account = client.account_info()
        spec = client.symbol_spec(symbol)
        tick = client.last_tick(symbol)
        flags = client.filling_flags(symbol)
        ours = [p for p in client.positions() if p.magic == dx.MAGIC]
    except BrokerError as exc:
        typer.echo(f"MT5 ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        client.shutdown()
    errors = dx.demo_guard_errors(settings, account)
    filling = {dx.ORDER_FILLING_FOK: "FOK", dx.ORDER_FILLING_IOC: "IOC",
               dx.ORDER_FILLING_RETURN: "RETURN"}[dx.filling_type(flags)]
    report = {
        "demo_orders_allowed": not errors,
        "blocking_reasons": errors,
        "account": {"server": account.server, "trade_mode": account.trade_mode,
                    "currency": account.currency, "balance": account.balance,
                    "leverage": account.leverage},
        "symbol": {"name": spec.symbol, "trade_allowed": spec.trade_allowed,
                   "short_allowed": spec.short_allowed, "volume_min": spec.volume_min,
                   "volume_step": spec.volume_step, "stops_level_points": spec.stops_level_points,
                   "spread_points_now": tick.spread_points, "filling": filling},
        "magic": dx.MAGIC,
        "open_positions_with_our_magic": len(ours),
    }
    typer.echo(json.dumps(report, indent=2, default=str))
    if errors:
        raise typer.Exit(code=3)


@mt5_app.command("check")
def mt5_check() -> None:
    """Connect to the MT5 terminal and print account and symbol info. Sends nothing.

    Exit 2 if the connected account is not a demo account.
    """
    settings = _settings_or_exit()
    client = _connected_client(settings)
    try:
        account = client.account_info()
        configured = settings.mt5_server_utc_offset_minutes
        report: dict[str, Any] = {
            "connected": client.is_connected(),
            "account": account.model_dump(),
            "server_utc_offset_minutes": {
                "configured": configured,
                "observed": client.probe_utc_offset_minutes(settings.default_symbol),
            },
            "symbols": {},
        }
        if configured is None:
            typer.echo(json.dumps(report, indent=2, default=str))
            observed = report["server_utc_offset_minutes"]["observed"]
            hint = f"={observed}" if observed is not None else " (market closed: retry when open)"
            typer.echo(f"ACTION: set MT5_SERVER_UTC_OFFSET_MINUTES{hint} in .env", err=True)
            raise typer.Exit(code=1)
        for symbol in settings.symbols:
            spec = client.symbol_spec(symbol)
            tick = client.last_tick(symbol)
            report["symbols"][symbol] = {
                "digits": spec.digits,
                "point": spec.point,
                "tick_value": spec.tick_value,
                "volume_min": spec.volume_min,
                "volume_step": spec.volume_step,
                "currency_profit": spec.currency_profit,
                "spread_points": tick.spread_points,
                "trade_allowed": spec.trade_allowed,
            }
        report["open_positions"] = len(client.positions())
    except BrokerError as exc:
        typer.echo(f"MT5 ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        client.shutdown()
    typer.echo(json.dumps(report, indent=2, default=str))
    if account.trade_mode != "demo":
        typer.echo(
            f"WARNING: account is '{account.trade_mode}', not demo. "
            "The system will refuse to trade on it.",
            err=True,
        )
        raise typer.Exit(code=2)


@data_app.command("download")
def data_download(
    symbol: Annotated[str, typer.Option(help="e.g. EURUSD")],
    start: Annotated[datetime, typer.Option(formats=["%Y-%m-%d"], help="UTC, inclusive")],
    end: Annotated[datetime, typer.Option(formats=["%Y-%m-%d"], help="UTC, exclusive")],
    timeframe: Annotated[Timeframe, typer.Option("--tf")] = Timeframe.M15,
    out: Annotated[Path, typer.Option(help="Output directory")] = DATASETS,
) -> None:
    """Download closed bars from MT5 to Parquet + manifest (with sha256)."""
    settings = _settings_or_exit()
    client = _connected_client(settings)
    try:
        path = history.download(
            client,
            symbol.upper(),
            timeframe,
            start.replace(tzinfo=UTC),
            end.replace(tzinfo=UTC),
            out,
        )
    except (BrokerError, ValueError) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        client.shutdown()
    typer.echo(f"OK {path}")


@data_app.command("fred")
def data_fred(
    start: Annotated[datetime, typer.Option(formats=["%Y-%m-%d"])] = datetime(2009, 1, 1),
    out: Annotated[Path, typer.Option(help="Output file")] = DATASETS / "fred_macro.json",
) -> None:
    """Download VIX, high-yield spread and 10Y-2Y curve daily history from FRED."""
    from trading_system.macro import fred_history

    settings = _settings_or_exit()
    if settings.fred_api_key is None:
        typer.echo("FRED_API_KEY is not set in .env", err=True)
        raise typer.Exit(code=1)
    key = settings.fred_api_key.get_secret_value()
    series = {}
    for sid in fred_history.SERIES:
        try:
            series[sid] = fred_history.fetch_series(sid, key, start.date())
        except (RuntimeError, httpx.HTTPError) as exc:
            typer.echo(f"ERROR {sid}: {type(exc).__name__}: {exc}", err=True)
            raise typer.Exit(code=1) from None
        obs = series[sid]
        typer.echo(f"{sid}: {len(obs)} obs {obs[0][0]} -> {obs[-1][0]}")
    fred_history.save(series, out)
    typer.echo(f"OK {out}")


@data_app.command("rates")
def data_rates(
    start: Annotated[datetime, typer.Option(formats=["%Y-%m-%d"])] = datetime(2005, 1, 1),
    out: Annotated[Path, typer.Option(help="Output file")] = DATASETS / RATES_FILE,
) -> None:
    """Download monthly 3-month interbank rates (FRED/OECD) for the 8 carry currencies."""
    from trading_system.macro import fred_history, rates

    settings = _settings_or_exit()
    if settings.fred_api_key is None:
        typer.echo("FRED_API_KEY is not set in .env", err=True)
        raise typer.Exit(code=1)
    key = settings.fred_api_key.get_secret_value()
    series = {}
    for ccy in rates.FRED_COUNTRY:
        try:
            series[ccy] = fred_history.fetch_series(rates.series_id(ccy), key, start.date())
        except (RuntimeError, httpx.HTTPError) as exc:
            typer.echo(f"ERROR {ccy}: {type(exc).__name__}: {exc}", err=True)
            raise typer.Exit(code=1) from None
        obs = series[ccy]
        typer.echo(f"{ccy}: {len(obs)} months {obs[0][0]} -> {obs[-1][0]}")
    fred_history.save(series, out)
    typer.echo(f"OK {out}")


def _write_report(result: dict[str, Any], out: Path) -> Path:
    from trading_system.backtest import report, runner

    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    stem = out / f"{stamp}-{result['label']}"
    stem.with_suffix(".json").write_text(json.dumps(result, indent=1, default=str),
                                         encoding="utf-8")
    stem.with_suffix(".md").write_text(report.render(result), encoding="utf-8")
    runner.log_experiment(result, EXPERIMENTS)
    for c in result["gate_a"]:
        typer.echo(f"{c['id']:>4} {c['status']:<8} {c['criterion']}: {c['value']}")
    typer.echo(f"Gate A passed: {result['gate_a_passed']}  ->  {stem.with_suffix('.md')}")
    return stem


def _load_rates(data: Path) -> Any:
    from trading_system.macro.fred_history import load as load_fred
    from trading_system.macro.rates import RateHistory

    rates_path = data / RATES_FILE
    if not rates_path.exists():
        typer.echo("missing rates: run `trading-system data rates` first", err=True)
        raise typer.Exit(code=1)
    return RateHistory(load_fred(rates_path))


@backtest_app.command("carry")
def backtest_carry(
    symbols: Annotated[str, typer.Option(help="Comma separated USD pairs")] = (
        "EURUSD,GBPUSD,AUDUSD,NZDUSD,USDJPY,USDCAD,USDCHF"),
    data: Annotated[Path, typer.Option(help="Datasets directory")] = DATASETS,
    out: Annotated[Path, typer.Option(help="Reports directory")] = REPORTS,
    neighbours: Annotated[bool, typer.Option(help="Run A9 stability variants")] = True,
    null_runs: NullRuns = NULL_RUNS,
) -> None:
    """Run carry-v001 (ADR 0004) on D1 with costs, swap, walk-forward and Gate A."""
    from trading_system.backtest import runner


    bars, hashes = runner.load_datasets(
        data, [s.strip().upper() for s in symbols.split(",")], Timeframe.D1)
    result = runner.run_carry_suite(
        bars, hashes, _load_rates(data), neighbours=neighbours, null_runs=null_runs,
        progress=lambda name: typer.echo(f"  running {name}...", err=True))
    _write_report(result, out)


@backtest_app.command("breakout")
def backtest_breakout(
    symbols: Annotated[str, typer.Option(help="Comma separated instruments")] = (
        "XAUUSD,XAGUSD,US500,US30,EURUSD,GBPUSD,AUDUSD,NZDUSD,USDJPY,USDCAD,USDCHF"),
    data: Annotated[Path, typer.Option(help="Datasets directory")] = DATASETS,
    out: Annotated[Path, typer.Option(help="Reports directory")] = REPORTS,
    neighbours: Annotated[bool, typer.Option(help="Run A9 stability variants")] = True,
    null_runs: NullRuns = NULL_RUNS,
) -> None:
    """Run breakout-v001 (ADR 0006) on D1, cent-equivalent capital, costs and financing."""
    from trading_system.backtest import runner


    bars, hashes = runner.load_datasets(
        data, [s.strip().upper() for s in symbols.split(",")], Timeframe.D1)
    result = runner.run_breakout_suite(
        bars, hashes, _load_rates(data), neighbours=neighbours, null_runs=null_runs,
        progress=lambda name: typer.echo(f"  running {name}...", err=True))
    _write_report(result, out)


@backtest_app.command("pairs")
def backtest_pairs(
    data: Annotated[Path, typer.Option(help="Datasets directory")] = DATASETS,
    out: Annotated[Path, typer.Option(help="Reports directory")] = REPORTS,
    neighbours: Annotated[bool, typer.Option(help="Run A9 stability variants")] = True,
) -> None:
    """Run pairs-v001 (ADR 0007): AUDUSD-NZDUSD statistical arbitrage on H1."""
    from trading_system.backtest import runner

    bars, hashes = runner.load_datasets(data, ["AUDUSD", "NZDUSD"], Timeframe.H1)
    result = runner.run_pairs_suite(
        bars, hashes, _load_rates(data), neighbours=neighbours,
        progress=lambda name: typer.echo(f"  running {name}...", err=True))
    _write_report(result, out)


@backtest_app.command("regime")
def backtest_regime(
    control: Annotated[bool, typer.Option(
        help="Run the unfiltered H4 breakout control (ADR 0008)")] = False,
    data: Annotated[Path, typer.Option(help="Datasets directory")] = DATASETS,
    out: Annotated[Path, typer.Option(help="Reports directory")] = REPORTS,
    neighbours: Annotated[bool, typer.Option(help="Run A9 stability variants")] = True,
    null_runs: NullRuns = NULL_RUNS,
) -> None:
    """Run regime-h4-v001 (H4 breakout + GMM regime filter) or its control (ADR 0008)."""
    from trading_system.backtest import runner

    symbols = ["XAUUSD", "XAGUSD", "US500", "US30", "EURUSD", "GBPUSD", "AUDUSD",
               "NZDUSD", "USDJPY", "USDCAD", "USDCHF"]
    bars, hashes = runner.load_datasets(data, symbols, Timeframe.H4)
    result = runner.run_regime_suite(
        bars, hashes, _load_rates(data), control=control, neighbours=neighbours,
        null_runs=null_runs, progress=lambda name: typer.echo(f"  running {name}...", err=True))
    _write_report(result, out)


@backtest_app.command("fibsr")
def backtest_fibsr(
    data: Annotated[Path, typer.Option(help="Datasets directory")] = DATASETS,
    out: Annotated[Path, typer.Option(help="Reports directory")] = REPORTS,
    neighbours: Annotated[bool, typer.Option(help="Run A9 stability variants")] = True,
    null_runs: NullRuns = NULL_RUNS,
) -> None:
    """Run fibsr-xau-v002 (ADR 0011/0012): gold Fibonacci + S/R, walk-forward over 12 variants."""
    from trading_system.backtest import fibsr_suite
    from trading_system.broker.history import file_sha256, read_bars

    since = datetime(2015, 7, 1, tzinfo=UTC)  # ADR 0011 addendum: research from 2016
    files = {tf: sorted(data.glob(f"XAUUSD_{tf}_*.parquet")) for tf in ("M5", "H1")}
    if not files["M5"] or not files["H1"]:
        typer.echo("missing XAUUSD M5/H1 datasets: run `trading-system data download`", err=True)
        raise typer.Exit(code=1)
    m5 = read_bars(files["M5"][-1], since=since)
    h1 = read_bars(files["H1"][-1], since=since)
    hashes = {"XAUUSD": file_sha256(files["M5"][-1]),
              "XAUUSD_H1": file_sha256(files["H1"][-1])}
    result = fibsr_suite.run_fibsr_suite(
        m5, h1, hashes, _load_rates(data), neighbours=neighbours, null_runs=null_runs,
        progress=lambda name: typer.echo(f"  running {name}...", err=True))
    _write_report(result, out)


@backtest_app.command("trend")
def backtest_trend(
    tf: Annotated[str, typer.Option(help="H1, H4 or D1 (H1 by ADR 0019)")] = "H4",
    exit_mode: Annotated[str, typer.Option(
        "--exit", help="channel, trailing, invalidation or target")] = "channel",
    trend_filter: Annotated[bool, typer.Option(help="EMA 50/200 filter (off = control)")] = True,
    target_r: Annotated[float, typer.Option(
        help="Take-profit in R for --exit target: 2.0 (ADR 0014) or 1.0 (ADR 0020)")] = 2.0,
    holdout: Annotated[bool, typer.Option(
        help="Evaluate the 12-month hold-out. ONCE only (ADR 0002); recorded.")] = False,
    data: Annotated[Path, typer.Option(help="Datasets directory")] = DATASETS,
    out: Annotated[Path, typer.Option(help="Reports directory")] = REPORTS,
    neighbours: Annotated[bool, typer.Option(help="Run A9 stability variants")] = True,
    null_runs: NullRuns = NULL_RUNS,
) -> None:
    """Run one version of trendbo-xau-v001 (ADR 0014): EMA 50/200 + 20-bar breakout on gold."""
    from trading_system.backtest import gates, runner, trend_suite
    from trading_system.strategy.trend_breakout import EXIT_MODES

    timeframe = Timeframe(tf.upper())
    if (timeframe not in trend_suite.TIMEFRAMES or exit_mode not in EXIT_MODES
            or not trend_suite.preregistered_target_r(target_r)):
        typer.echo(f"pre-registered: --tf H1|H4|D1, --exit {'|'.join(EXIT_MODES)}, "
                   "--target-r 2.0|1.0", err=True)
        raise typer.Exit(code=2)
    bars, hashes = runner.load_datasets(data, [trend_suite.SYMBOL], timeframe)
    if holdout:
        if not typer.confirm("The hold-out can be evaluated only once. Continue?"):
            raise typer.Exit(code=1)
        try:
            gates.claim_holdout(out / "holdout_used.json",
                                trend_suite.version_name(timeframe, exit_mode, trend_filter,
                                                         target_r))
        except gates.HoldoutAlreadyUsedError as exc:
            typer.echo(f"REFUSED: {exc}", err=True)
            raise typer.Exit(code=2) from None
    result = trend_suite.run_trend_suite(
        bars[trend_suite.SYMBOL], hashes, _load_rates(data), timeframe=timeframe,
        exit_mode=exit_mode, target_r=target_r,
        trend_filter=trend_filter, holdout=holdout, neighbours=neighbours, null_runs=null_runs,
        progress=lambda name: typer.echo(f"  running {name}...", err=True))
    _write_report(result, out)


@backtest_app.command("trend-basket")
def backtest_trend_basket(
    data: Annotated[Path, typer.Option(help="Datasets directory")] = DATASETS,
    out: Annotated[Path, typer.Option(help="Reports directory")] = REPORTS,
    neighbours: Annotated[bool, typer.Option(help="Run A9 stability variants")] = True,
    null_runs: NullRuns = NULL_RUNS,
) -> None:
    """Run trendbo-basket-h4-channel (ADR 0019): frozen gold H4 rules on the ADR 0006 basket."""
    from trading_system.backtest import runner, trend_suite

    bars, hashes = runner.load_datasets(data, list(trend_suite.BASKET), Timeframe.H4)
    result = trend_suite.run_trend_basket(
        bars, hashes, _load_rates(data), neighbours=neighbours, null_runs=null_runs,
        progress=lambda name: typer.echo(f"  running {name}...", err=True))
    _write_report(result, out)


@backtest_app.command("run")
def backtest_run(
    symbols: Annotated[str, typer.Option(help="Comma separated")] = "EURUSD,GBPUSD,USDJPY",
    data: Annotated[Path, typer.Option(help="Datasets directory")] = DATASETS,
    out: Annotated[Path, typer.Option(help="Reports directory")] = REPORTS,
    holdout: Annotated[bool, typer.Option(
        help="Evaluate the 12-month hold-out. ONCE only (ADR 0002); recorded.")] = False,
    neighbours: Annotated[bool, typer.Option(help="Run A9 stability variants")] = True,
    null_runs: NullRuns = NULL_RUNS,
    timeframe: Annotated[Timeframe, typer.Option("--tf", help="Bar timeframe")] = Timeframe.M15,
    macro_filter: Annotated[str, typer.Option(
        help="none | block | confirm (ADR 0003, needs `data fred`)")] = "none",
) -> None:
    """Run baseline-v001 with costs x1/x1.5/x2, walk-forward and Gate A. Writes a report."""
    from trading_system.backtest import gates, runner
    from trading_system.macro.fred_history import FredMacroHistory
    from trading_system.macro.fred_history import load as load_fred
    from trading_system.strategy.baseline import BaselineParams

    if macro_filter not in ("none", "block", "confirm"):
        typer.echo("--macro-filter must be none, block or confirm", err=True)
        raise typer.Exit(code=1)
    # Each timeframe / filter is its own hypothesis with its own version (ADR 0002 budget).
    version = "baseline-v001" if timeframe is Timeframe.M15 else (
        f"baseline-v001-{timeframe.value.lower()}")
    params = BaselineParams(timeframe=timeframe, version=version)
    macro, macro_source = None, "unknown (no history)"
    if macro_filter != "none":
        fred_path = data / "fred_macro.json"
        if not fred_path.exists():
            typer.echo("missing FRED history: run `trading-system data fred` first", err=True)
            raise typer.Exit(code=1)
        macro = FredMacroHistory(load_fred(fred_path)).context_at
        macro_source = "FRED daily history (available D+1 22:00 UTC), regime-rules-v001"
        params = params.model_copy(update={
            "version": f"{version}-macro-{macro_filter}",
            "macro_required": True,
            "macro_require_confirmation": macro_filter == "confirm",
        })
    bars, hashes = runner.load_datasets(
        data, [s.strip().upper() for s in symbols.split(",")], timeframe)
    if holdout:
        if not typer.confirm("The hold-out can be evaluated only once. Continue?"):
            raise typer.Exit(code=1)
        try:
            gates.claim_holdout(out / "holdout_used.json", version)
        except gates.HoldoutAlreadyUsedError as exc:
            typer.echo(f"REFUSED: {exc}", err=True)
            raise typer.Exit(code=2) from None
    result = runner.run_suite(bars, hashes, params=params, macro=macro, macro_source=macro_source,
                              holdout=holdout, neighbours=neighbours, null_runs=null_runs,
                              progress=lambda name: typer.echo(f"  running {name}...", err=True))
    _write_report(result, out)


@macro_app.command("check")
def macro_check() -> None:
    """Query Crucix once and print the normalized MacroContext. Exit 1 if unknown."""
    settings = _settings_or_exit()
    client = _crucix(settings)
    try:
        healthy = client.healthy()
        context = client.current()
    finally:
        client.close()
    typer.echo(json.dumps({"healthy": healthy, "context": context.model_dump(mode="json")},
                          indent=2))
    if context.risk_regime == "unknown":
        raise typer.Exit(code=1)


@macro_app.command("record")
def macro_record(
    interval_minutes: Annotated[int, typer.Option(min=1)] = 15,
    once: Annotated[bool, typer.Option(help="Record a single snapshot and exit")] = False,
    out: Annotated[Path, typer.Option(help="Output directory")] = recorder.DEFAULT_DIR,
    wait_minutes: Annotated[
        int, typer.Option(min=0, help="Wait up to N minutes for Crucix data before the first one")
    ] = 0,
) -> None:
    """Append Crucix snapshots to monthly JSONL files. This builds the macro history."""
    settings = _settings_or_exit()
    client = _crucix(settings)
    try:
        with recorder.single_instance(out):
            if not recorder.wait_for_data(client, timedelta(minutes=wait_minutes)):
                typer.echo("Crucix data not available yet; recording anyway", err=True)
            while True:
                ctx = recorder.record_once(client, out)
                typer.echo(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S}Z {ctx.risk_regime} "
                           f"conf={ctx.confidence} stale={ctx.data_stale}")
                if once:
                    break
                time.sleep(interval_minutes * 60)
    except recorder.AlreadyRunningError as exc:
        typer.echo(f"NOT STARTED: {exc}", err=True)
        raise typer.Exit(code=3) from None
    except KeyboardInterrupt:
        typer.echo("stopped")
    finally:
        client.close()



@paper_app.command("tick")
def paper_tick(
    db: Annotated[Path, typer.Option(help="Paper trading SQLite file")] = PAPER_DB,
) -> None:
    """Process the H4 bars closed since the last run (idempotent; schedule every 5 min)."""
    from trading_system.storage.paper_store import PaperStore
    from trading_system.workers.paper_loop import PaperTrader

    store = PaperStore(db)
    client = _connected_client(_settings_or_exit())
    try:
        outcome = PaperTrader(client, store).tick()
    except BrokerError as exc:
        store.record_run(datetime.now(UTC), "error", str(exc))
        typer.echo(f"MT5 ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        client.shutdown()
    typer.echo(f"{outcome.status} bars={outcome.bars} {outcome.detail}".rstrip())


@paper_app.command("report")
def paper_report(
    db: Annotated[Path, typer.Option(help="Paper trading SQLite file")] = PAPER_DB,
    check_parity: Annotated[bool, typer.Option(
        "--parity/--no-parity", help="Re-run the backtest on the same bars (needs MT5)")] = True,
) -> None:
    """Paper summary (signals, trades, observed spread) and parity with the backtest."""
    from trading_system.storage.paper_store import PaperStore
    from trading_system.workers import paper_report as report
    from trading_system.workers.paper_loop import PaperConfig, frozen_params

    if not db.exists():
        typer.echo(f"no paper store at {db}; run `paper tick` first", err=True)
        raise typer.Exit(code=1)
    store = PaperStore(db)
    result: dict[str, Any] = {"summary": report.summary(store)}
    if check_parity:
        cfg, params = PaperConfig(), frozen_params()
        client = _connected_client(_settings_or_exit())
        try:
            bars = client.closed_bars(cfg.symbol, params.timeframe, cfg.history_bars)
        finally:
            client.shutdown()
        result["parity"] = report.parity(store, bars, params, cfg.capital)
    typer.echo(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    app()
