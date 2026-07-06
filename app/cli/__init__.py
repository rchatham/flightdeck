"""FlightDeck CLI — Click + Rich client for the FlightDeck API.

Entrypoint registered in pyproject.toml as `flightdeck`.
"""
import click

from app.cli.commands.db import db_cmd
from app.cli.commands.fares import fares_cmd
from app.cli.commands.health import health_cmd
from app.cli.commands.scrape import scrape_cmd
from app.cli.commands.search import search_cmd
from app.cli.commands.timing import timing_cmd
from app.cli.commands.watch import watch_cmd


@click.group(help="FlightDeck — flight search, analysis, and price tracking.")
@click.option(
    "--api-url",
    envvar="FLIGHTDECK_CLI_API_URL",
    default=None,
    help="Override the API base URL (default: http://localhost:8001).",
)
@click.pass_context
def cli(ctx: click.Context, api_url: str | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["api_url"] = api_url


cli.add_command(health_cmd)
cli.add_command(db_cmd)
cli.add_command(search_cmd)
cli.add_command(scrape_cmd)
cli.add_command(timing_cmd)
cli.add_command(fares_cmd)
cli.add_command(watch_cmd)


if __name__ == "__main__":
    cli()
