"""System status for the web dashboard's Settings tab.

Mirrors `flightdeck health`, but over HTTP — the CLI reads `.env` directly
in its own process; browser JS can't, so it needs a server-side endpoint.
Reports presence only, never values: no key or webhook URL is ever returned.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.services.health import check_postgres, check_redis

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/status")
async def system_status() -> dict:
    settings = get_settings()
    pg_status, pg_detail = await check_postgres()
    redis_status, redis_detail = await check_redis()
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
    }
