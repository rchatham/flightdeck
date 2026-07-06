"""Route optimizer service.

Steps 4–6: multi-source fan-out (Amadeus + Kiwi + SerpAPI), dedup across sources,
rank via the `score_offer` hook, persist Search + FlightOffer rows.

Public entrypoint: `run_search(session, request)` — accepts a SearchRequest schema,
returns the persisted Search ID + ranked list of FlightOffer rows.

Each source is called in parallel via asyncio.gather. A failing source logs a
warning and is skipped — never blocks the response.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.search import SearchRequest
from app.integrations.amadeus import AmadeusClient, AmadeusError
from app.integrations.kiwi import KiwiClient, KiwiError
from app.integrations.serpapi import SerpApiClient, SerpApiError
from app.integrations.types import NormalizedOffer
from app.models import FlightOffer, Search
from app.services.dedup import dedupe_offers
from app.services.ranking import RankingPreferences, score_offer

logger = logging.getLogger(__name__)


async def _search_amadeus(req: SearchRequest) -> list[NormalizedOffer]:
    async with AmadeusClient() as client:
        try:
            return await client.search_flight_offers(
                origin=req.origin,
                destination=req.destination,
                departure_date=req.departure_date,
                return_date=req.return_date,
                adults=req.passengers,
                cabin_class=req.cabin_class,
                non_stop=(req.max_stops == 0),
            )
        except AmadeusError as e:
            logger.warning("Amadeus search failed: %s", e)
            return []
        except Exception as e:  # noqa: BLE001
            logger.exception("Amadeus search crashed: %s", e)
            return []


async def _search_kiwi(req: SearchRequest) -> list[NormalizedOffer]:
    async with KiwiClient() as client:
        try:
            return await client.search_flight_offers(
                origin=req.origin,
                destination=req.destination,
                departure_date=req.departure_date,
                return_date=req.return_date,
                adults=req.passengers,
                cabin_class=req.cabin_class,
                non_stop=(req.max_stops == 0),
                virtually_interlined=False,
            )
        except KiwiError as e:
            logger.warning("Kiwi search failed: %s", e)
            return []
        except Exception as e:  # noqa: BLE001
            logger.exception("Kiwi search crashed: %s", e)
            return []


async def _search_serpapi(req: SearchRequest) -> list[NormalizedOffer]:
    async with SerpApiClient() as client:
        try:
            return await client.search_flight_offers(
                origin=req.origin,
                destination=req.destination,
                departure_date=req.departure_date,
                return_date=req.return_date,
                adults=req.passengers,
                cabin_class=req.cabin_class,
                non_stop=(req.max_stops == 0),
            )
        except SerpApiError as e:
            logger.warning("SerpAPI search failed: %s", e)
            return []
        except Exception as e:  # noqa: BLE001
            logger.exception("SerpAPI search crashed: %s", e)
            return []


async def _fan_out_sources(req: SearchRequest) -> list[NormalizedOffer]:
    """Run all configured sources in parallel; flatten the results."""
    results = await asyncio.gather(
        _search_amadeus(req),
        _search_kiwi(req),
        _search_serpapi(req),
        return_exceptions=False,  # already swallowed inside each helper
    )
    flat: list[NormalizedOffer] = []
    for source_offers in results:
        flat.extend(source_offers)
    return flat


def _to_db_offer(search_id, n: NormalizedOffer) -> FlightOffer:
    return FlightOffer(
        search_id=search_id,
        source=n.source,
        price_usd=n.price_usd,
        currency=n.currency,
        total_duration=n.total_duration,
        stops=n.stops,
        segments=[
            {
                "carrier": s.carrier,
                "flight_no": s.flight_no,
                "origin": s.origin,
                "destination": s.destination,
                "depart_at": s.depart_at.isoformat(),
                "arrive_at": s.arrive_at.isoformat(),
                "duration_seconds": int(s.duration.total_seconds()),
                "cabin": s.cabin,
            }
            for s in n.segments
        ],
        fare_type=n.fare_type,
        booking_url=n.booking_url,
        deep_link=n.deep_link,
        expires_at=n.expires_at,
    )


async def run_search(
    session: AsyncSession,
    req: SearchRequest,
    prefs: RankingPreferences | None = None,
) -> tuple[Search, Sequence[FlightOffer]]:
    """Persist a Search row, fan out to sources, dedup, rank, persist offers.

    Returns offers sorted by `score_offer` (lower = better).
    """
    prefs = prefs or RankingPreferences()

    search = Search(
        origin=req.origin,
        destination=req.destination,
        departure_date=req.departure_date,
        return_date=req.return_date,
        flex_days=req.flex_days,
        passengers=req.passengers,
        cabin_class=req.cabin_class,
        include_nearby=req.include_nearby,
    )
    session.add(search)
    await session.flush()  # populate search.id

    # Fan out to Amadeus + Kiwi + SerpAPI in parallel; failed sources are logged
    # and skipped, never block the response.
    normalized: list[NormalizedOffer] = await _fan_out_sources(req)

    # Dedup across sources, then rank via the user's score_offer hook
    deduped = dedupe_offers(normalized)
    cheapest = min((d.offer.price_usd for d in deduped), default=None)
    scored = [score_offer(d.offer, prefs, cheapest_price=cheapest) for d in deduped]
    scored.sort(key=lambda s: s.score)

    db_offers = [_to_db_offer(search.id, s.offer) for s in scored]
    session.add_all(db_offers)
    await session.commit()

    for o in db_offers:
        await session.refresh(o)
    return search, db_offers
