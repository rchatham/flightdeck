"""`flightdeck book` — booking handoff for a priced offer."""
from __future__ import annotations

import click
from rich.panel import Panel

from app.cli.client import APIClient, safe_json
from app.cli.output import console, emit

_KIND_STYLES = {
    "airline_direct": ("green", "BEST PROTECTION"),
    "source": ("cyan", "THIS EXACT FARE"),
    "google_flights": ("yellow", "VERIFY PRICE"),
}


def render_booking_links(payload: dict) -> None:
    console.print(f"[bold]{payload['context']}[/bold]\n")
    if not payload["links"]:
        console.print("[yellow]No booking links available for this offer.[/yellow]")
        return
    for link in payload["links"]:
        color, badge = _KIND_STYLES.get(link["kind"], ("white", link["kind"]))
        console.print(Panel(
            f"[link={link['url']}]{link['url']}[/link]\n[dim]{link['note']}[/dim]",
            title=f"[bold {color}]{badge}[/bold {color}] · {link['label']}",
            border_style=color,
        ))


@click.command("book", help="Show booking options for an offer from search results.")
@click.argument("offer_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def book_cmd(ctx: click.Context, offer_id: str, as_json: bool) -> None:
    api_url = ctx.obj.get("api_url") if ctx.obj else None
    client = APIClient(base_url=api_url)
    try:
        resp = client.get(f"/api/v1/offers/{offer_id}/booking")
    finally:
        client.close()
    emit(safe_json(resp), as_json=as_json, render_human=render_booking_links)
