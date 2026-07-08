"""`flightdeck points` — track balances and estimate award-redemption value."""
from __future__ import annotations

from uuid import UUID

import click
from rich.table import Table

from app.cli.client import APIClient, fail, safe_json
from app.cli.output import console, emit


@click.group("points", help="Track points balances and estimate redemption value.")
def points_cmd() -> None:
    pass


def _client(ctx: click.Context) -> APIClient:
    api_url = ctx.obj.get("api_url") if ctx.obj else None
    return APIClient(base_url=api_url)


def _resolve_program(client: APIClient, identifier: str) -> dict:
    """Accept either a program UUID or a case-insensitive name substring —
    typing a UUID for one of 4 seeded programs is needless friction."""
    try:
        UUID(identifier)
        resp = client.get(f"/api/v1/points/{identifier}")
        if resp.status_code == 200:
            return safe_json(resp)
    except ValueError:
        pass
    payload = safe_json(client.get("/api/v1/points"))
    matches = [p for p in payload["programs"] if identifier.lower() in p["program_name"].lower()]
    if not matches:
        fail(f"no points program matching '{identifier}'")
    if len(matches) > 1:
        names = ", ".join(p["program_name"] for p in matches)
        fail(f"'{identifier}' matches multiple programs ({names}) — be more specific")
    return matches[0]


def _render_list(payload: dict) -> None:
    if not payload["count"]:
        console.print("[yellow]No points programs seeded.[/yellow]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("Program")
    t.add_column("Card", style="dim")
    t.add_column("Balance", justify="right")
    t.add_column("Partners", justify="right")
    for p in payload["programs"]:
        t.add_row(p["program_name"], p.get("card_name") or "—",
                  f"{p['balance']:,}", str(len(p["transfer_partners"])))
    console.print(t)


def _render_partners(payload: dict) -> None:
    console.print(f"[bold]{payload['program_name']}[/bold] "
                  f"[dim]{payload.get('card_name') or ''}[/dim] — {payload['balance']:,} points")
    if not payload["transfer_partners"]:
        console.print("[dim]No transfer partners on file.[/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("Airline")
    t.add_column("IATA")
    t.add_column("Ratio")
    t.add_column("Bonus", justify="right")
    for tp in payload["transfer_partners"]:
        bonus = f"+{tp['bonus_pct']:.0f}%" if tp["bonus_pct"] else "—"
        t.add_row(tp["airline"], tp["iata"], tp["ratio"], bonus)
    console.print(t)


def _render_estimate(payload: dict) -> None:
    console.print(f"[bold]${float(payload['cash_price_usd']):,.0f}[/bold] redeemed as points:\n")
    t = Table(show_header=True, header_style="bold")
    t.add_column("Program")
    t.add_column("Value", justify="right")
    t.add_column("Points needed", justify="right")
    t.add_column("Balance", justify="right")
    t.add_column("Status")
    for e in payload["estimates"]:
        status = ("[green]✓ enough[/green]" if e["sufficient"]
                 else f"[red]short {e['shortfall']:,}[/red]")
        t.add_row(e["program_name"], f"{e['cents_per_point']:.2f}¢/pt",
                  f"{e['points_needed']:,}", f"{e['balance']:,}", status)
    console.print(t)


@points_cmd.command("list", help="List points programs and balances.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def points_list_cmd(ctx: click.Context, as_json: bool) -> None:
    client = _client(ctx)
    try:
        resp = client.get("/api/v1/points")
    finally:
        client.close()
    emit(safe_json(resp), as_json=as_json, render_human=_render_list)


@points_cmd.command("partners", help="Show transfer partners for a program (name or id).")
@click.argument("program")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def points_partners_cmd(ctx: click.Context, program: str, as_json: bool) -> None:
    client = _client(ctx)
    try:
        payload = _resolve_program(client, program)
    finally:
        client.close()
    emit(payload, as_json=as_json, render_human=_render_partners)


@points_cmd.command("set-balance", help="Update a program's balance (name or id).")
@click.argument("program")
@click.argument("balance", type=int)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def points_set_balance_cmd(ctx: click.Context, program: str, balance: int, as_json: bool) -> None:
    client = _client(ctx)
    try:
        row = _resolve_program(client, program)
        resp = client.patch(f"/api/v1/points/{row['id']}", json={"balance": balance})
    finally:
        client.close()
    emit(safe_json(resp), as_json=as_json, render_human=_render_partners)


@points_cmd.command("estimate", help="Estimate points needed across programs for a cash price.")
@click.argument("cash_price_usd", type=float)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def points_estimate_cmd(ctx: click.Context, cash_price_usd: float, as_json: bool) -> None:
    client = _client(ctx)
    try:
        resp = client.post("/api/v1/points/estimate", json={"cash_price_usd": cash_price_usd})
    finally:
        client.close()
    emit(safe_json(resp), as_json=as_json, render_human=_render_estimate)
