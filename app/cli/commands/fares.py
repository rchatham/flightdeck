"""`flightdeck fares` — discover hidden-city, split-ticket, and other unconventional fare strategies."""
from __future__ import annotations

from typing import Any

import click
from rich.panel import Panel
from rich.table import Table

from app.cli.client import APIClient, safe_json
from app.cli.output import console, emit


@click.group("fares", help="Hidden-city, split-ticket, and other unconventional fares.")
def fares_cmd() -> None:
    pass


_RISK_COLOR = {
    "LOW": "green",
    "MEDIUM": "yellow",
    "HIGH": "red",
    "EXTREME": "bold red",
    "DISQUALIFIED": "dim",
}


def _render_opportunities(payload: dict) -> None:
    if payload["opportunity_count"] == 0:
        console.print(
            f"[yellow]No hidden-fare opportunities found for "
            f"{payload['origin']}→{payload['destination']} on {payload['departure_date']}.[/yellow]"
        )
        if payload.get("direct_price_usd") is not None:
            console.print(f"[dim]Direct fare: ${float(payload['direct_price_usd']):,.2f}[/dim]")
        return

    if payload.get("direct_price_usd") is not None:
        console.print(
            f"[bold]{payload['origin']} → {payload['destination']}[/bold] "
            f"on {payload['departure_date']}  "
            f"[dim](direct fare: ${float(payload['direct_price_usd']):,.2f})[/dim]"
        )

    for i, opp in enumerate(payload["opportunities"], 1):
        risk_color = _RISK_COLOR.get(opp["overall_risk"], "white")
        title = (
            f"#{i}: {opp['strategy']}  "
            f"[bold {risk_color}]{opp['overall_risk']}[/bold {risk_color}]"
        )

        # Body: savings + reasoning + flags + booking steps
        savings_line = (
            f"[bold green]Save ${float(opp['savings_usd']):,.2f}[/bold green] "
            f"({opp['savings_pct']:.1f}%) — booked at "
            f"${float(opp['price_usd']):,.2f}"
        )
        body_lines = [savings_line, "", opp["risk_reasoning"]]

        if opp["risk_flags"]:
            body_lines.append("")
            body_lines.append("[bold]Risks:[/bold]")
            for f in opp["risk_flags"]:
                fc = _RISK_COLOR.get(f["severity"], "white")
                body_lines.append(f"  [{fc}]●[/{fc}] {f['description']}")

        if opp.get("booking_steps"):
            body_lines.append("")
            body_lines.append("[bold]How to book:[/bold]")
            for step in opp["booking_steps"]:
                body_lines.append(f"  • {step}")

        # Real vs final destination for hidden_city is the most important detail
        if opp["real_destination"] != opp["final_destination"]:
            body_lines.append("")
            body_lines.append(
                f"[bold yellow]⚠ Get off at {opp['real_destination']}, "
                f"NOT {opp['final_destination']}[/bold yellow]"
            )

        console.print(Panel("\n".join(body_lines), title=title, border_style=risk_color))


@fares_cmd.command("hidden", help="Discover hidden-city, split-ticket, and other strategies.")
@click.argument("origin")
@click.argument("destination")
@click.argument("departure_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--return-date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--passengers", type=int, default=1)
@click.option("--cabin", "cabin_class", default="economy")
@click.option("--strategies", default="hidden_city,split_ticket",
              help="Comma-separated subset of: hidden_city, split_ticket, multi_city.")
@click.option("--has-checked-bag", is_flag=True, default=False,
              help="Set if you'll be checking bags — affects risk scoring.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def fares_hidden_cmd(
    ctx: click.Context,
    origin: str,
    destination: str,
    departure_date: Any,
    return_date: Any | None,
    passengers: int,
    cabin_class: str,
    strategies: str,
    has_checked_bag: bool,
    as_json: bool,
) -> None:
    body = {
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_date": (
            departure_date.date().isoformat() if hasattr(departure_date, "date") else str(departure_date)
        ),
        "passengers": passengers,
        "cabin_class": cabin_class,
        "strategies": [s.strip() for s in strategies.split(",") if s.strip()],
        "has_checked_bag": has_checked_bag,
    }
    if return_date:
        body["return_date"] = (
            return_date.date().isoformat() if hasattr(return_date, "date") else str(return_date)
        )

    api_url = ctx.obj.get("api_url") if ctx.obj else None
    client = APIClient(base_url=api_url, timeout=120.0)
    try:
        if not as_json:
            console.print(
                f"[dim]Searching hidden-fare opportunities for "
                f"{body['origin']}→{body['destination']} on {body['departure_date']}...[/dim]"
            )
        resp = client.post("/api/v1/fares/hidden", json=body)
    finally:
        client.close()

    payload = safe_json(resp)
    emit(payload, as_json=as_json, render_human=_render_opportunities)
