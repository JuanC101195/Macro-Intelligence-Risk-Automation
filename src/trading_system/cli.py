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
from trading_system.broker import history
from trading_system.broker.mt5_client import BrokerError, Mt5Client
from trading_system.config import ConfigurationError, Settings, load_settings
from trading_system.domain import Timeframe
from trading_system.macro import recorder
from trading_system.macro.crucix_client import CrucixClient

app = typer.Typer(help="Intelligence Trading Platform", no_args_is_help=True)
config_app = typer.Typer(help="Configuration commands", no_args_is_help=True)
mt5_app = typer.Typer(help="MetaTrader 5 (read-only)", no_args_is_help=True)
data_app = typer.Typer(help="Historical data", no_args_is_help=True)
macro_app = typer.Typer(help="Crucix macro context", no_args_is_help=True)
backtest_app = typer.Typer(help="Backtests and ADR 0002 gates", no_args_is_help=True)
app.add_typer(backtest_app, name="backtest")
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
    out: Annotated[Path, typer.Option(help="Output directory")] = Path("research/datasets"),
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
    out: Annotated[Path, typer.Option(help="Output file")] = Path(
        "research/datasets/fred_macro.json"),
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


@backtest_app.command("run")
def backtest_run(
    symbols: Annotated[str, typer.Option(help="Comma separated")] = "EURUSD,GBPUSD,USDJPY",
    data: Annotated[Path, typer.Option(help="Datasets directory")] = Path("research/datasets"),
    out: Annotated[Path, typer.Option(help="Reports directory")] = Path("research/reports"),
    holdout: Annotated[bool, typer.Option(
        help="Evaluate the 12-month hold-out. ONCE only (ADR 0002); recorded.")] = False,
    neighbours: Annotated[bool, typer.Option(help="Run A9 stability variants")] = True,
    timeframe: Annotated[Timeframe, typer.Option("--tf", help="Bar timeframe")] = Timeframe.M15,
    macro_filter: Annotated[str, typer.Option(
        help="none | block | confirm (ADR 0003, needs `data fred`)")] = "none",
) -> None:
    """Run baseline-v001 with costs x1/x1.5/x2, walk-forward and Gate A. Writes a report."""
    from trading_system.backtest import gates, report, runner
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
                              holdout=holdout, neighbours=neighbours,
                              progress=lambda name: typer.echo(f"  running {name}...", err=True))
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    stem = out / f"{stamp}-{result['label']}"
    stem.with_suffix(".json").write_text(json.dumps(result, indent=1, default=str),
                                         encoding="utf-8")
    stem.with_suffix(".md").write_text(report.render(result), encoding="utf-8")
    runner.log_experiment(result, Path("research/experiments.jsonl"))
    for c in result["gate_a"]:
        typer.echo(f"{c['id']:>4} {c['status']:<8} {c['criterion']}: {c['value']}")
    typer.echo(f"Gate A passed: {result['gate_a_passed']}  ->  {stem.with_suffix('.md')}")


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


if __name__ == "__main__":
    app()
