"""`flightdeck health` — verify API, Postgres, Redis, and API-key presence."""
from __future__ import annotations

import asyncio

import click
import httpx
import redis.asyncio as redis_asyncio
from sqlalchemy import text

from app.cli.client import APIClient
from app.cli.output import console, emit, status_table
from app.config import get_settings
from app.db import get_engine


async def _check_postgres() -> tuple[str, str]:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok", get_settings().database_url.split("@")[-1]
    except Exception as e:  # noqa: BLE001
        return "error", str(e)[:120]


async def _check_redis() -> tuple[str, str]:
    try:
        client = redis_asyncio.from_url(get_settings().redis_url)
        await client.ping()
        await client.aclose()
        return "ok", get_settings().redis_url
    except Exception as e:  # noqa: BLE001
        return "error", str(e)[:120]


def _check_api(api_url: str | None) -> tuple[str, str]:
    client = APIClient(base_url=api_url)
    try:
        resp = client.get("/health", timeout=2.0)
        if resp.status_code == 200:
            return "ok", client.base_url
        return "error", f"{resp.status_code} {resp.reason_phrase}"
    except httpx.HTTPError as e:
        return "error", str(e)[:120]
    finally:
        client.close()


def _check_api_keys() -> list[tuple[str, str, str]]:
    s = get_settings()
    return [
        ("Amadeus key", "ok" if s.amadeus_api_key else "missing",
         "set" if s.amadeus_api_key else "AMADEUS_API_KEY not set in .env"),
        ("Amadeus secret", "ok" if s.amadeus_api_secret else "missing",
         "set" if s.amadeus_api_secret else "AMADEUS_API_SECRET not set in .env"),
        ("Kiwi Tequila key", "ok" if s.kiwi_api_key else "missing",
         "set" if s.kiwi_api_key else "KIWI_API_KEY not set in .env"),
        ("SerpAPI key", "ok" if s.serpapi_api_key else "missing",
         "set" if s.serpapi_api_key else "SERPAPI_API_KEY not set in .env"),
    ]


async def _gather_checks(api_url: str | None) -> dict:
    pg_status, pg_detail = await _check_postgres()
    redis_status, redis_detail = await _check_redis()
    api_status, api_detail = _check_api(api_url)
    keys = _check_api_keys()
    return {
        "postgres": {"status": pg_status, "detail": pg_detail},
        "redis": {"status": redis_status, "detail": redis_detail},
        "api": {"status": api_status, "detail": api_detail},
        "api_keys": [
            {"name": n, "status": s, "detail": d} for n, s, d in keys
        ],
    }


def _render_human(report: dict) -> None:
    rows: list[tuple[str, str, str]] = [
        ("API", report["api"]["status"], report["api"]["detail"]),
        ("Postgres", report["postgres"]["status"], report["postgres"]["detail"]),
        ("Redis", report["redis"]["status"], report["redis"]["detail"]),
    ]
    for k in report["api_keys"]:
        rows.append((k["name"], k["status"], k["detail"]))
    console.print(status_table(rows))


@click.command("health", help="Check API, Postgres, Redis, and API-key configuration.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_context
def health_cmd(ctx: click.Context, as_json: bool) -> None:
    api_url = ctx.obj.get("api_url") if ctx.obj else None
    report = asyncio.run(_gather_checks(api_url))
    emit(report, as_json=as_json, render_human=_render_human)
    # Non-zero exit if any critical component is broken
    critical_fail = any(report[k]["status"] != "ok" for k in ("postgres", "redis", "api"))
    if critical_fail:
        ctx.exit(1)
