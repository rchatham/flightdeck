"""`flightdeck scrape` — manually run the price-history scraper.

Useful for backfilling history, verifying the worker pipeline without firing
up Celery, or one-off testing of new routes before adding them to the daily
schedule.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

import click

from app.cli.output import console, emit
from app.workers.price_history_scraper import POPULAR_ROUTES, _scrape_route_async


@click.group("scrape", help="Manually trigger price-history scraping.")
def scrape_cmd() -> None:
    pass


@scrape_cmd.command("route", help="Scrape a single route + date.")
@click.argument("origin")
@click.argument("destination")
@click.argument("departure_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def scrape_route_cmd(origin: str, destination: str, departure_date, as_json: bool) -> None:
    dep = departure_date.date() if hasattr(departure_date, "date") else departure_date
    if not as_json:
        console.print(f"[dim]Scraping {origin.upper()}→{destination.upper()} "
                      f"for {dep.isoformat()}...[/dim]")
    result = asyncio.run(_scrape_route_async(origin.upper(), destination.upper(), dep))

    def _render(payload):
        if payload.get("offers_found", 0) == 0:
            console.print(f"[yellow]No offers found — nothing recorded for "
                          f"{payload['route']} on {payload['departure_date']}.[/yellow]")
        else:
            console.print(
                f"[green]✓[/green] Recorded cheapest offer "
                f"${payload['cheapest_price_usd']:,.2f} for {payload['route']} "
                f"on {payload['departure_date']} ({payload['offers_found']} offers seen)."
            )

    emit(result, as_json=as_json, render_human=_render)


@scrape_cmd.command("popular", help="Scrape all popular routes (the daily-beat task).")
@click.option("--json", "as_json", is_flag=True)
def scrape_popular_cmd(as_json: bool) -> None:
    """Run the same task that Celery beat fires daily, but synchronously here."""
    from app.workers.price_history_scraper import scrape_popular_routes
    if not as_json:
        console.print(f"[dim]Scraping {len(POPULAR_ROUTES)} routes "
                      f"× 4 sample days = {len(POPULAR_ROUTES) * 4} (route, date) "
                      f"combinations...[/dim]")
    result = scrape_popular_routes()  # Celery task, but callable directly

    def _render(payload):
        ok = sum(1 for r in payload["runs"] if r.get("offers_found", 0) > 0)
        skip = sum(1 for r in payload["runs"] if r.get("offers_found") == 0)
        err = sum(1 for r in payload["runs"] if r.get("error"))
        console.print(f"[green]✓[/green] Recorded: {ok}  "
                      f"[yellow]No offers: {skip}[/yellow]  "
                      f"[red]Errors: {err}[/red]  "
                      f"of {payload['total_routes']} runs.")

    emit(result, as_json=as_json, render_human=_render)


@scrape_cmd.command("list-routes", help="List the routes the daily beat scrapes.")
@click.option("--json", "as_json", is_flag=True)
def scrape_list_routes_cmd(as_json: bool) -> None:
    routes = [{"origin": o, "destination": d} for o, d in POPULAR_ROUTES]
    emit(routes, as_json=as_json,
         render_human=lambda _: console.print(
             "\n".join(f"  {o}→{d}" for o, d in POPULAR_ROUTES)))
