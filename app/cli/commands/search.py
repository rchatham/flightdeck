"""`flightdeck search` — search for flights."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import click
from rich.table import Table

from app.cli.client import APIClient, safe_json
from app.cli.output import console, emit


def _humanize_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h{m:02d}m"


def _humanize_segments(segments: list[dict]) -> str:
    """e.g. SFO→ICN→NRT (UA)  for a 1-stop itinerary."""
    if not segments:
        return ""
    path = segments[0]["origin"]
    carriers = set()
    for s in segments:
        path += f"→{s['destination']}"
        carriers.add(s["carrier"])
    return f"{path} ({','.join(sorted(carriers))})"


def _render_results(payload: dict) -> None:
    offers = payload.get("offers", [])
    if not offers:
        console.print(f"[yellow]No offers found for {payload['origin']}→{payload['destination']} "
                      f"on {payload['departure_date']}[/yellow]")
        return

    console.print(
        f"[bold]{payload['origin']} → {payload['destination']}[/bold]  "
        f"[dim]on {payload['departure_date']} · search_id={payload['search_id']}[/dim]"
    )

    has_legs = any(o.get("leg") for o in offers)

    t = Table(show_header=True, header_style="bold")
    t.add_column("#", justify="right", style="dim")
    if has_legs:
        t.add_column("Leg")
    t.add_column("Price (USD)", justify="right")
    t.add_column("Stops", justify="right")
    t.add_column("Duration", justify="right")
    t.add_column("Route")
    t.add_column("Source", style="dim")
    t.add_column("Offer ID", style="dim")

    # Naive sort by price for human display (search response is unsorted today).
    sorted_offers = sorted(offers, key=lambda o: float(o["price_usd"]))
    for i, o in enumerate(sorted_offers, 1):
        td = o.get("total_duration")
        # FastAPI emits timedelta as ISO 8601 duration string by default; convert
        if isinstance(td, str):
            duration_secs = _iso_to_seconds(td)
        else:
            duration_secs = td if td is None else float(td)
        row = [str(i)]
        if has_legs:
            row.append(o.get("leg") or "—")
        row += [
            f"${float(o['price_usd']):,.2f}",
            str(o["stops"]),
            _humanize_duration(duration_secs),
            _humanize_segments(o.get("segments", [])),
            o.get("source", "?"),
            str(o["id"])[:8],
        ]
        t.add_row(*row)
    if has_legs:
        console.print("[dim]Open-jaw: outbound/return priced as separate one-way fares.[/dim]")
    console.print(t)
    console.print(f"[dim]{len(offers)} offers · sorted by price[/dim]")


def _iso_to_seconds(s: str) -> float | None:
    """Parse 'PT12H35M' → seconds."""
    if not s.startswith("P"):
        return None
    body = s[1:]
    days = hours = minutes = seconds = 0
    if "T" in body:
        date_part, time_part = body.split("T", 1)
    else:
        date_part, time_part = body, ""
    if date_part.endswith("D"):
        days = int(date_part[:-1])
    num = ""
    for ch in time_part:
        if ch.isdigit():
            num += ch
        elif ch == "H":
            hours = int(num)
            num = ""
        elif ch == "M":
            minutes = int(num)
            num = ""
        elif ch == "S":
            seconds = int(num)
            num = ""
    total = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    return float(total.total_seconds())


@click.command("search", help="Search for flights between two airports.")
@click.argument("origin")
@click.argument("destination")
@click.argument("departure_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--return-date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None,
              help="Round-trip return date (YYYY-MM-DD).")
@click.option("--return-origin", default=None,
              help="Open-jaw: return leg departs here instead of DESTINATION.")
@click.option("--return-destination", default=None,
              help="Open-jaw: return leg arrives here instead of ORIGIN.")
@click.option("--flex", "flex_days", type=int, default=0, help="±N days flexibility.")
@click.option("--passengers", type=int, default=1)
@click.option("--cabin", "cabin_class", type=click.Choice(
    ["economy", "premium_economy", "business", "first"]), default="economy")
@click.option("--max-stops", type=int, default=None)
@click.option("--no-nearby", is_flag=True, default=False, help="Don't expand to nearby airports.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_context
def search_cmd(
    ctx: click.Context,
    origin: str,
    destination: str,
    departure_date: Any,
    return_date: Any | None,
    return_origin: str | None,
    return_destination: str | None,
    flex_days: int,
    passengers: int,
    cabin_class: str,
    max_stops: int | None,
    no_nearby: bool,
    as_json: bool,
) -> None:
    departure_date_str = (
        departure_date.date().isoformat() if hasattr(departure_date, "date")
        else str(departure_date)
    )
    body = {
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_date": departure_date_str,
        "flex_days": flex_days,
        "passengers": passengers,
        "cabin_class": cabin_class,
        "include_nearby": not no_nearby,
    }
    if return_date:
        body["return_date"] = (
            return_date.date().isoformat() if hasattr(return_date, "date") else str(return_date)
        )
    if max_stops is not None:
        body["max_stops"] = max_stops
    if return_origin:
        body["return_origin"] = return_origin.upper()
    if return_destination:
        body["return_destination"] = return_destination.upper()

    api_url = ctx.obj.get("api_url") if ctx.obj else None
    client = APIClient(base_url=api_url, timeout=60.0)
    try:
        if not as_json:
            console.print(
                f"[dim]Searching {body['origin']}→{body['destination']} "
                f"for {body['departure_date']}...[/dim]"
            )
        resp = client.post("/api/v1/routes/search", json=body)
    finally:
        client.close()

    payload = safe_json(resp)
    emit(payload, as_json=as_json, render_human=_render_results)


# Lightweight `date` type registration for help text
_ = date
