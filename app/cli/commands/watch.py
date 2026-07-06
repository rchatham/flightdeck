"""`flightdeck watch` — track specific trips and surface price alerts."""
from __future__ import annotations

from typing import Any

import click
from rich.panel import Panel
from rich.table import Table

from app.cli.client import APIClient, safe_json
from app.cli.output import console, emit


@click.group("watch", help="Track specific trips; alert when the price is right.")
def watch_cmd() -> None:
    pass


_KIND_COLORS = {
    "target_hit": "green",
    "new_low": "cyan",
    "price_drop": "green",
    "price_spike": "red",
}


def _fmt_price(value: Any) -> str:
    return f"${float(value):,.0f}" if value is not None else "—"


def _render_watch(payload: dict) -> None:
    target = _fmt_price(payload.get("target_price_usd"))
    body = (
        f"[bold]{payload['origin']} → {payload['destination']}[/bold]  "
        f"{payload['departure_date']}"
        + (f" ⇄ {payload['return_date']}" if payload.get("return_date") else "")
        + f"  [dim]{payload['cabin_class']}[/dim]\n"
        f"target {target} · last seen {_fmt_price(payload.get('last_price_usd'))} · "
        f"lowest {_fmt_price(payload.get('lowest_seen_usd'))}"
    )
    status = "green" if payload["active"] else "dim"
    console.print(Panel(body, title=f"watch {payload['id']}", border_style=status))


def _render_watch_list(payload: dict) -> None:
    if payload["count"] == 0:
        console.print("[yellow]No watches yet.[/yellow]")
        console.print("[dim]Try: flightdeck watch add SFO NRT 2026-10-15 --target 800[/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("ID", style="dim", max_width=8)
    t.add_column("Route")
    t.add_column("Departs")
    t.add_column("Target", justify="right")
    t.add_column("Last", justify="right")
    t.add_column("Lowest", justify="right")
    t.add_column("Checked", style="dim")
    for w in payload["watches"]:
        t.add_row(
            str(w["id"])[:8],
            f"{w['origin']}→{w['destination']}",
            w["departure_date"],
            _fmt_price(w.get("target_price_usd")),
            _fmt_price(w.get("last_price_usd")),
            _fmt_price(w.get("lowest_seen_usd")),
            (w.get("last_checked_at") or "never")[:16],
        )
    console.print(t)


def _render_alerts(payload: dict) -> None:
    if payload["count"] == 0:
        console.print("[green]No unacknowledged alerts.[/green]")
        return
    for a in payload["alerts"]:
        color = _KIND_COLORS.get(a["kind"], "white")
        console.print(Panel(
            f"[bold {color}]{a['kind'].upper()}[/bold {color}]  "
            f"{_fmt_price(a['price_usd'])}"
            + (f" [dim](was {_fmt_price(a['previous_price_usd'])})[/dim]"
               if a.get("previous_price_usd") else "")
            + f"\n{a['message']}",
            title=f"alert {str(a['id'])[:8]} · {a['created_at'][:16]}",
            border_style=color,
        ))


def _render_check(payload: dict) -> None:
    if payload.get("deactivated"):
        console.print("[yellow]Watch deactivated — departure date has passed.[/yellow]")
        return
    console.print(
        f"Checked: [bold]{payload['offers_found']}[/bold] offers, "
        f"cheapest {_fmt_price(payload.get('cheapest_price_usd'))}"
    )
    if payload["alert_fired"]:
        _render_alerts({"count": 1, "alerts": [payload["alert"]]})
    else:
        console.print("[dim]No alert fired.[/dim]")
    _render_watch(payload["watch"])


def _client(ctx: click.Context) -> APIClient:
    api_url = ctx.obj.get("api_url") if ctx.obj else None
    return APIClient(base_url=api_url)


@watch_cmd.command("add", help="Watch a trip: ORIGIN DEST DEPARTURE_DATE.")
@click.argument("origin")
@click.argument("destination")
@click.argument("departure_date", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--return-date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--target", type=float, default=None, help="Alert at/below this price (USD).")
@click.option("--cabin", default="economy",
              type=click.Choice(["economy", "premium_economy", "business", "first"]))
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def watch_add_cmd(ctx, origin, destination, departure_date, return_date, target, cabin, as_json):
    body = {
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_date": departure_date.date().isoformat(),
        "cabin_class": cabin,
    }
    if return_date is not None:
        body["return_date"] = return_date.date().isoformat()
    if target is not None:
        body["target_price_usd"] = target
    client = _client(ctx)
    try:
        resp = client.post("/api/v1/watches", json=body)
    finally:
        client.close()
    emit(safe_json(resp), as_json=as_json, render_human=_render_watch)


@watch_cmd.command("list", help="List watches.")
@click.option("--all", "include_inactive", is_flag=True, help="Include inactive watches.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def watch_list_cmd(ctx, include_inactive, as_json):
    client = _client(ctx)
    try:
        resp = client.get("/api/v1/watches",
                          params={"include_inactive": include_inactive})
    finally:
        client.close()
    emit(safe_json(resp), as_json=as_json, render_human=_render_watch_list)


@watch_cmd.command("rm", help="Delete a watch by id.")
@click.argument("watch_id")
@click.pass_context
def watch_rm_cmd(ctx, watch_id):
    client = _client(ctx)
    try:
        resp = client.delete(f"/api/v1/watches/{watch_id}")
    finally:
        client.close()
    if resp.status_code == 204:
        console.print(f"[green]Deleted watch {watch_id}.[/green]")
    else:
        emit(safe_json(resp), as_json=True, render_human=None)


@watch_cmd.command("check", help="Run a live price check on a watch right now.")
@click.argument("watch_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def watch_check_cmd(ctx, watch_id, as_json):
    client = _client(ctx)
    try:
        resp = client.post(f"/api/v1/watches/{watch_id}/check")
    finally:
        client.close()
    emit(safe_json(resp), as_json=as_json, render_human=_render_check)


@watch_cmd.command("alerts", help="Show fired alerts (unacknowledged by default).")
@click.option("--all", "include_acknowledged", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def watch_alerts_cmd(ctx, include_acknowledged, as_json):
    client = _client(ctx)
    try:
        resp = client.get("/api/v1/watches/alerts",
                          params={"include_acknowledged": include_acknowledged})
    finally:
        client.close()
    emit(safe_json(resp), as_json=as_json, render_human=_render_alerts)


@watch_cmd.command("book", help="Show booking options for a watched trip.")
@click.argument("watch_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def watch_book_cmd(ctx, watch_id, as_json):
    from app.cli.commands.book import render_booking_links

    client = _client(ctx)
    try:
        resp = client.get(f"/api/v1/watches/{watch_id}/booking")
    finally:
        client.close()
    emit(safe_json(resp), as_json=as_json, render_human=render_booking_links)


@watch_cmd.command("ack", help="Acknowledge an alert so it stops showing.")
@click.argument("alert_id")
@click.pass_context
def watch_ack_cmd(ctx, alert_id):
    client = _client(ctx)
    try:
        resp = client.post(f"/api/v1/watches/alerts/{alert_id}/ack")
    finally:
        client.close()
    payload = safe_json(resp)
    console.print(f"[green]Acknowledged alert {str(payload.get('id', alert_id))[:8]}.[/green]")
