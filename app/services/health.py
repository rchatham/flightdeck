"""Infrastructure health checks — shared by the CLI (`flightdeck health`) and
the web dashboard's Settings tab (`GET /api/v1/system/status`).

The CLI checks run in the operator's own process and can read `.env`
directly. Browser JS has no such access, so the API needs its own endpoint
that reports the same checks without ever exposing secret values.
"""
from __future__ import annotations

import redis.asyncio as redis_asyncio
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine


async def check_postgres() -> tuple[str, str]:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok", get_settings().database_url.split("@")[-1]
    except Exception as e:  # noqa: BLE001
        return "error", str(e)[:160]


async def check_redis() -> tuple[str, str]:
    try:
        client = redis_asyncio.from_url(get_settings().redis_url)
        await client.ping()
        await client.aclose()
        return "ok", get_settings().redis_url
    except Exception as e:  # noqa: BLE001
        return "error", str(e)[:160]
