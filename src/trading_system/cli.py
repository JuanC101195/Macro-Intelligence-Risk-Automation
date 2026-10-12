"""Command line entry point: `trading-system ...`."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

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
