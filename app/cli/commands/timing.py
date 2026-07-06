"""`flightdeck timing` — booking-window analysis from price history."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import click
from rich.panel import Panel
from rich.table import Table

from app.cli.client import APIClient, safe_json
from app.cli.output import console, emit


@click.group("timing", help="Booking-window analysis from price history.")
def timing_cmd() -> None:
    pass


def _verdict_color(verdict: str) -> str:
    return {
        "BUY_NOW": "green",
        "WAIT": "yellow",
        "NEUTRAL": "cyan",
        "TOO_CLOSE_TO_CALL": "dim",
    }.get(verdict, "white")


def _render_analyze(payload: dict) -> None:
    color = _verdict_color(payload["verdict"])
    confidence_pct = int(payload["confidence"] * 100)

    header = (
        f"[bold]{payload['route']}[/bold] for {payload['departure_date']} "
        f"[dim]({payload['days_until_departure']} days out)[/dim]"
    )
    body = (
        f"[bold {color}]{payload['verdict']}[/bold {color}]  "
        f"[dim](confidence {confidence_pct}%)[/dim]\n\n"
        f"{payload['reasoning']}"
    )
    extras = []
    if payload.get("median_price") is not None:
        extras.append(f"median ${float(payload['median_price']):,.0f}")
    if payload.get("current_pct_above_median") is not None:
        v = payload["current_pct_above_median"]
        sign = "+" if v >= 0 else ""
        extras.append(f"current {sign}{v:.1f}% vs median")
    extras.append(f"{payload['sample_count']} samples")
    if extras:
        body += f"\n\n[dim]{' · '.join(extras)}[/dim]"

    console.print(Panel(body, title=header, border_style=color))


def _render_history(payload: dict) -> None:
    if payload["point_count"] == 0:
        console.print(f"[yellow]No history yet for {payload['route_key']}.[/yellow]")
        console.print("[dim]Try: flightdeck scrape route <ORIGIN> <DEST> <YYYY-MM-DD>[/dim]")
        return

    t = Table(show_header=True, header_style="bold")
    t.add_column("Recorded")
    t.add_column("Price (USD)", justify="right")
    t.add_column("Days to dep", justify="right", style="dim")

    for p in payload["points"][-25:]:  # show most recent 25
        rec_at = datetime.fromisoformat(p["recorded_at"]).strftime("%Y-%m-%d %H:%M")
        t.add_row(rec_at, f"${float(p['price_usd']):,.2f}",
                  str(p["days_until_departure"]) if p["days_until_departure"] is not None else "—")
    console.print(f"[bold]{payload['route_key']}[/bold]  "
                  f"[dim]({payload['point_count']} points; showing last 25)[/dim]")
    console.print(t)


@timing_cmd.command("analyze", help="Recommend a booking action for a route + date.")
@click.argument("origin")
@click.argument("destination")
@click.argument("departure_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--current-price", type=float, default=None,
              help="Current cheapest price (USD), if you have one to compare to history.")
@click.option("--lookback-days", type=int, default=180)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def timing_analyze_cmd(
    ctx: click.Context,
    origin: str,
    destination: str,
    departure_date: Any,
    current_price: float | None,
    lookback_days: int,
    as_json: bool,
) -> None:
    api_url = ctx.obj.get("api_url") if ctx.obj else None
    client = APIClient(base_url=api_url)
    params = {
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_date": (
            departure_date.date().isoformat() if hasattr(departure_date, "date") else str(departure_date)
        ),
        "lookback_days": lookback_days,
    }
    if current_price is not None:
        params["current_price"] = current_price
    try:
        resp = client.get("/api/v1/timing/analyze", params=params)
    finally:
        client.close()
    payload = safe_json(resp)
    emit(payload, as_json=as_json, render_human=_render_analyze)


@timing_cmd.command("history", help="Show stored price-history points for a route.")
@click.argument("route_key")
@click.option("--lookback-days", type=int, default=180)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def timing_history_cmd(
    ctx: click.Context, route_key: str, lookback_days: int, as_json: bool
) -> None:
    api_url = ctx.obj.get("api_url") if ctx.obj else None
    client = APIClient(base_url=api_url)
    try:
        resp = client.get(
            "/api/v1/timing/history",
            params={"route_key": route_key, "lookback_days": lookback_days},
        )
    finally:
        client.close()
    payload = safe_json(resp)
    emit(payload, as_json=as_json, render_human=_render_history)
