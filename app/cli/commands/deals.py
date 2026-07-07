"""`flightdeck deals` — cheapest-day scans and location resolution."""
from __future__ import annotations

from typing import Any

import click
from rich.panel import Panel
from rich.table import Table

from app.cli.client import APIClient, safe_json
from app.cli.commands.book import render_booking_links
from app.cli.output import console, emit

_RISK_COLORS = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "EXTREME": "red"}


@click.group("deals", help="Find the cheapest days to fly between two locations.")
def deals_cmd() -> None:
    pass


def _render_resolve(payload: dict) -> None:
    if not payload["airports"]:
        console.print(f"[yellow]No airports found for '{payload['query']}'.[/yellow]")
        return
    console.print(f"[bold]{payload['label']}[/bold] [dim]({payload['kind']})[/dim]")
    t = Table(show_header=True, header_style="bold")
    t.add_column("Code")
    t.add_column("Airport")
    t.add_column("City")
    t.add_column("Distance", justify="right")
    for a in payload["airports"]:
        t.add_row(a["iata_code"], a["name"], f"{a['city']}, {a['country']}",
                  f"{a['distance_km']:,.0f} km")
    console.print(t)


def _tier_cell(b: dict) -> str:
    if b["tier"] == "DEAL":
        return f"[bold green]DEAL {b['vs_median_pct']:+.0f}%[/bold green]"
    if b["tier"] == "GOOD":
        return f"[green]GOOD {b['vs_median_pct']:+.0f}%[/green]"
    if b.get("vs_median_pct") is not None:
        return f"[dim]{b['vs_median_pct']:+.0f}% vs median[/dim]"
    return "[dim]no history[/dim]"


def _render_scan(payload: dict) -> None:
    console.print(
        f"[bold]{payload['origin_label']}[/bold] ({'/'.join(payload['origin_airports'])})"
        f" → [bold]{payload['destination_label']}[/bold]"
        f" ({'/'.join(payload['destination_airports'])})  "
        f"[dim]{payload['date_from']} … {payload['date_to']} · "
        f"{payload['searches_run']} searches[/dim]"
    )
    if not payload["by_date"]:
        console.print("[yellow]No offers found across the window. Without fare-source "
                      "API keys every search returns empty — check `flightdeck health`.[/yellow]")
        return

    t = Table(show_header=True, header_style="bold")
    t.add_column("Depart")
    t.add_column("Route")
    t.add_column("Price", justify="right")
    t.add_column("Stops", justify="right")
    t.add_column("Deal?")
    best = payload["best"]
    for b in payload["by_date"]:
        is_best = best and b["departure_date"] == best["departure_date"]
        mark = "[bold green]★ [/bold green]" if is_best else "  "
        t.add_row(
            mark + b["departure_date"],
            f"{b['origin']}→{b['destination']}",
            f"${float(b['price_usd']):,.0f}",
            str(b["stops"]),
            _tier_cell(b),
        )
    console.print(t)

    if best:
        console.print(Panel(
            f"Leave [bold]{best['departure_date']}[/bold]"
            + (f", return {best['return_date']}" if best.get("return_date") else "")
            + f" — [bold]${float(best['price_usd']):,.0f}[/bold] "
            f"{best['origin']}→{best['destination']} via {best['source']}",
            title="[bold green]Best day to fly[/bold green]", border_style="green",
        ))
        render_booking_links({"context": "", "links": payload["booking_links"]})

    for opp in payload["opportunities"]:
        color = _RISK_COLORS.get(opp["risk_level"], "yellow")
        steps = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(opp["booking_steps"]))
        console.print(Panel(
            f"[bold]${float(opp['price_usd']):,.0f}[/bold] "
            f"(saves ${float(opp['savings_usd']):,.0f}, {opp['savings_pct']:.0f}%)  "
            f"[bold {color}]{opp['risk_level']} RISK[/bold {color}]\n"
            f"{opp['risk_reasoning']}\n{steps}",
            title=f"Hacker fare: {opp['strategy'].replace('_', ' ')}",
            border_style=color,
        ))


@deals_cmd.command("scan", help="Scan a date window for the cheapest day to fly.")
@click.argument("origin")
@click.argument("destination")
@click.option("--from", "date_from", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
@click.option("--to", "date_to", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
@click.option("--trip-length", type=int, default=None, help="Round-trip length in days.")
@click.option("--cabin", default="economy",
              type=click.Choice(["economy", "premium_economy", "business", "first"]))
@click.option("--max-searches", type=int, default=12, help="Cap on live fan-outs (1-40).")
@click.option("--no-nearby", is_flag=True, help="Exact airports only; skip geo expansion.")
@click.option("--hacker-fares", is_flag=True,
              help="Run hidden-city/split-ticket discovery on the best find.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def deals_scan_cmd(ctx: click.Context, origin: str, destination: str,
                   date_from: Any, date_to: Any, trip_length: int | None,
                   cabin: str, max_searches: int, no_nearby: bool,
                   hacker_fares: bool, as_json: bool) -> None:
    body = {
        "origin": origin, "destination": destination,
        "date_from": date_from.date().isoformat(),
        "date_to": date_to.date().isoformat(),
        "cabin_class": cabin, "max_searches": max_searches,
        "include_nearby": not no_nearby,
        "include_hacker_fares": hacker_fares,
    }
    if trip_length is not None:
        body["trip_length_days"] = trip_length
    api_url = ctx.obj.get("api_url") if ctx.obj else None
    client = APIClient(base_url=api_url, timeout=180.0)  # scans fan out widely
    try:
        resp = client.post("/api/v1/deals/scan", json=body)
    finally:
        client.close()
    emit(safe_json(resp), as_json=as_json, render_human=_render_scan)


@deals_cmd.command("airports", help="Resolve a city, IATA code, or 'lat,lon' to nearby airports.")
@click.argument("query")
@click.option("--radius-km", type=float, default=150.0)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def deals_airports_cmd(ctx: click.Context, query: str, radius_km: float, as_json: bool) -> None:
    api_url = ctx.obj.get("api_url") if ctx.obj else None
    client = APIClient(base_url=api_url)
    try:
        resp = client.get("/api/v1/airports/resolve",
                          params={"q": query, "radius_km": radius_km})
    finally:
        client.close()
    emit(safe_json(resp), as_json=as_json, render_human=_render_resolve)
