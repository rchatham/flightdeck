"""System status for the web dashboard's Settings tab.

Mirrors `flightdeck health`, but over HTTP — the CLI reads `.env` directly
in its own process; browser JS can't, so it needs a server-side endpoint.
Reports presence only, never values: no key or webhook URL is ever returned.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import PriceWatch
from app.services.health import check_postgres, check_redis

router = APIRouter(prefix="/api/v1/system", tags=["system"])

# Beat runs check_all_watches every 6h; past this we've likely missed a cycle.
STALE_THRESHOLD_HOURS = 7


@router.get("/status")
async def system_status(session: AsyncSession = Depends(get_session)) -> dict:
    settings = get_settings()
    pg_status, pg_detail = await check_postgres()
    redis_status, redis_detail = await check_redis()

    active_count = (
        await session.execute(
            select(func.count()).select_from(PriceWatch).where(PriceWatch.active.is_(True))
        )
    ).scalar_one()
    stalest_checked_at = (
        await session.execute(
            select(func.min(PriceWatch.last_checked_at)).where(PriceWatch.active.is_(True))
        )
    ).scalar_one()

    stalest_check_age_hours: float | None = None
    stale = False
    if stalest_checked_at is not None:
        age = datetime.now(UTC) - stalest_checked_at
        stalest_check_age_hours = age.total_seconds() / 3600
        stale = stalest_check_age_hours > STALE_THRESHOLD_HOURS

    return {
        "postgres": {"status": pg_status, "detail": pg_detail},
        "redis": {"status": redis_status, "detail": redis_detail},
        "fare_sources": {
            "amadeus": bool(settings.amadeus_api_key and settings.amadeus_api_secret),
            "kiwi": bool(settings.kiwi_api_key),
            "serpapi": bool(settings.serpapi_api_key),
        },
        "notifications": {
            "ntfy": bool(settings.ntfy_topic),
            "webhook": bool(settings.alert_webhook_url),
        },
        "watches": {
            "active_count": active_count,
            "stalest_check_age_hours": stalest_check_age_hours,
            "stale": stale,
        },
    }
