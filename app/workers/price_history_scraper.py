"""Daily price-history scraper.

Records the cheapest offer found for each (route, departure_date) pair into
the `price_history` table. The Hook 2 timing analyzer reads from this table
to recommend booking windows.

Two task entry points:
  • `scrape_route(origin, dest, departure_date_iso)` — manual one-off, useful
    for backfills and CLI testing.
  • `scrape_popular_routes()` — beat-scheduled daily; iterates a fixed list of
    high-interest routes spanning the next 90 days.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.search import SearchRequest
from app.db import session_scope
from app.integrations.types import NormalizedOffer
from app.models import PriceHistory
from app.services.route_optimizer import _fan_out_sources
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# Hand-curated route list. The set is intentionally small for the MVP — we'd
# rather have dense history on a few routes than thin history on hundreds.
# Add to this list as your travel patterns evolve.
POPULAR_ROUTES: list[tuple[str, str]] = [
    ("SFO", "NRT"),
    ("SFO", "LHR"),
    ("SFO", "JFK"),
    ("SFO", "LAX"),
    ("LAX", "LHR"),
    ("LAX", "NRT"),
    ("JFK", "LHR"),
    ("JFK", "CDG"),
    ("ORD", "LHR"),
]

# How many future-departure dates to sample per route per scrape run.
# 4 dates × 9 routes = 36 API calls per day. Within most free-tier quotas.
SAMPLE_DAYS_AHEAD = [14, 30, 60, 90]


def _route_key(origin: str, destination: str, departure_date: date | None = None) -> str:
    """'SFO-NRT' for any-date or 'SFO-NRT:2026-04-15' for a date-pinned key."""
    base = f"{origin.upper()}-{destination.upper()}"
    return f"{base}:{departure_date.isoformat()}" if departure_date else base


async def _record_cheapest(
    session: AsyncSession,
    origin: str,
    destination: str,
    departure_date: date,
    offers: list[NormalizedOffer],
) -> Decimal | None:
    """Append a row to price_history for the cheapest offer in `offers`."""
    if not offers:
        return None
    cheapest = min(offers, key=lambda o: o.price_usd)
    days_until = (departure_date - date.today()).days
    row = PriceHistory(
        route_key=_route_key(origin, destination, departure_date),
        price_usd=cheapest.price_usd,
        source=cheapest.source,
        cabin_class="economy",
        days_until_departure=days_until,
    )
    session.add(row)
    await session.commit()
    return cheapest.price_usd


async def _scrape_route_async(origin: str, destination: str, departure_date: date) -> dict:
    req = SearchRequest(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        passengers=1,
        cabin_class="economy",
        include_nearby=False,
    )
    offers = await _fan_out_sources(req)
    async with session_scope() as session:
        cheapest = await _record_cheapest(session, origin, destination, departure_date, offers)
    return {
        "route": f"{origin}-{destination}",
        "departure_date": departure_date.isoformat(),
        "offers_found": len(offers),
        "cheapest_price_usd": float(cheapest) if cheapest is not None else None,
    }


@celery_app.task(
    name="app.workers.price_history_scraper.scrape_route",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    acks_late=True,
)
def scrape_route(origin: str, destination: str, departure_date_iso: str) -> dict:
    """Scrape one (route, date) and record the cheapest. Sync wrapper for Celery."""
    departure_date = date.fromisoformat(departure_date_iso)
    return asyncio.run(_scrape_route_async(origin, destination, departure_date))


@celery_app.task(
    name="app.workers.price_history_scraper.scrape_popular_routes",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    acks_late=True,
)
def scrape_popular_routes() -> dict:
    """Scrape every (popular_route, sample_day) combination."""
    today = date.today()
    summary = {"runs": [], "total_routes": 0}

    async def _run_all() -> list[dict]:
        results = []
        for origin, dest in POPULAR_ROUTES:
            for days_ahead in SAMPLE_DAYS_AHEAD:
                departure = today + timedelta(days=days_ahead)
                try:
                    results.append(await _scrape_route_async(origin, dest, departure))
                except Exception as e:  # noqa: BLE001
                    logger.exception("scrape failed for %s-%s on %s: %s",
                                     origin, dest, departure, e)
                    results.append({
                        "route": f"{origin}-{dest}",
                        "departure_date": departure.isoformat(),
                        "error": str(e)[:120],
                    })
        return results

    runs = asyncio.run(_run_all())
    summary["runs"] = runs
    summary["total_routes"] = len(runs)
    summary["completed_at"] = datetime.now(UTC).isoformat()
    return summary
