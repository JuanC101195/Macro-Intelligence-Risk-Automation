"""Command line entry point: `trading-system ...`."""

from __future__ import annotations

import json

import typer

from trading_system import __version__
from trading_system.config import ConfigurationError, load_settings

app = typer.Typer(help="Intelligence Trading Platform", no_args_is_help=True)
config_app = typer.Typer(help="Configuration commands", no_args_is_help=True)
app.add_typer(config_app, name="config")


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@config_app.command("check")
def config_check() -> None:
    """Validate the current configuration (.env + environment). Exit 1 if unsafe."""
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        typer.echo(f"INVALID: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo("OK")
    typer.echo(json.dumps(settings.public_summary(), indent=2))


if __name__ == "__main__":
    app()
