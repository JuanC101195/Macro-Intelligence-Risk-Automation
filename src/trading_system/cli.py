"""Command line entry point: `trading-system ...`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from trading_system import __version__
from trading_system.broker import history
from trading_system.broker.mt5_client import BrokerError, Mt5Client
from trading_system.config import ConfigurationError, Settings, load_settings
from trading_system.domain import Timeframe

app = typer.Typer(help="Intelligence Trading Platform", no_args_is_help=True)
config_app = typer.Typer(help="Configuration commands", no_args_is_help=True)
mt5_app = typer.Typer(help="MetaTrader 5 (read-only)", no_args_is_help=True)
data_app = typer.Typer(help="Historical data", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(mt5_app, name="mt5")
app.add_typer(data_app, name="data")


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


if __name__ == "__main__":
    app()
