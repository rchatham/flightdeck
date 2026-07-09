"""Scheduled checker for active price watches.

Every run: load active watches, fan out a live search for each, record the
observation, and let the Hook 4 alert rule decide whether to fire an alert.

Two task entry points:
  • `check_watch_by_id(watch_id)` — one-off, used for manual re-checks.
  • `check_all_watches()` — beat-scheduled every 6 hours.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.db import session_scope
from app.models import PriceWatch
from app.services.watches import check_watch
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _check_all_async() -> list[dict]:
    results: list[dict] = []
    async with session_scope() as session:
        watches = (
            await session.execute(select(PriceWatch).where(PriceWatch.active.is_(True)))
        ).scalars().all()
        for watch in watches:
            label = f"{watch.origin}-{watch.destination}:{watch.departure_date.isoformat()}"
            try:
                outcome = await check_watch(session, watch)
                results.append({
                    "watch": label,
                    "offers_found": outcome.offers_found,
                    "cheapest_price_usd": (
                        float(outcome.cheapest_price_usd)
                        if outcome.cheapest_price_usd is not None else None
                    ),
                    "alert_fired": outcome.alert is not None,
                    "deactivated": outcome.deactivated,
                })
            except Exception as e:  # noqa: BLE001
                logger.exception("watch check failed for %s: %s", label, e)
                results.append({"watch": label, "error": str(e)[:120]})
    return results


@celery_app.task(
    name="app.workers.watch_checker.check_all_watches",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    acks_late=True,
)
def check_all_watches() -> dict:
    """Check every active watch. Sync wrapper for Celery."""
    runs = asyncio.run(_check_all_async())
    return {
        "watches_checked": len(runs),
        "alerts_fired": sum(1 for r in runs if r.get("alert_fired")),
        "runs": runs,
        "completed_at": datetime.now(UTC).isoformat(),
    }


async def _check_one_async(watch_id: str) -> dict:
    async with session_scope() as session:
        watch = await session.get(PriceWatch, watch_id)
        if watch is None:
            return {"error": f"watch {watch_id} not found"}
        outcome = await check_watch(session, watch)
        return {
            "watch": f"{watch.origin}-{watch.destination}:{watch.departure_date.isoformat()}",
            "offers_found": outcome.offers_found,
            "cheapest_price_usd": (
                float(outcome.cheapest_price_usd)
                if outcome.cheapest_price_usd is not None else None
            ),
            "alert_fired": outcome.alert is not None,
            "deactivated": outcome.deactivated,
        }


@celery_app.task(
    name="app.workers.watch_checker.check_watch_by_id",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    acks_late=True,
)
def check_watch_by_id(watch_id: str) -> dict:
    """Check a single watch by id. Sync wrapper for Celery."""
    return asyncio.run(_check_one_async(watch_id))
