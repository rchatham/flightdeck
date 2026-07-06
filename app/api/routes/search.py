"""Flight search endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.search import OfferOut, SearchRequest, SearchResponse, SegmentOut
from app.db import get_session
from app.models import FlightOffer, Search
from app.services.route_optimizer import run_search

router = APIRouter(prefix="/api/v1/routes", tags=["search"])


def _segments_to_out(segments: list[dict]) -> list[SegmentOut]:
    from datetime import datetime, timedelta
    return [
        SegmentOut(
            carrier=s["carrier"],
            flight_no=s["flight_no"],
            origin=s["origin"],
            destination=s["destination"],
            depart_at=datetime.fromisoformat(s["depart_at"]),
            arrive_at=datetime.fromisoformat(s["arrive_at"]),
            duration=timedelta(seconds=s["duration_seconds"]),
            cabin=s["cabin"],
        )
        for s in segments
    ]


def _offer_to_out(o: FlightOffer) -> OfferOut:
    return OfferOut(
        id=o.id,
        source=o.source,
        price_usd=o.price_usd,
        currency=o.currency,
        total_duration=o.total_duration,
        stops=o.stops,
        segments=_segments_to_out(o.segments),
        fare_type=o.fare_type or "regular",
        booking_url=o.booking_url,
        deep_link=o.deep_link,
    )


@router.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest, session: AsyncSession = Depends(get_session)
) -> SearchResponse:
    search, offers = await run_search(session, req)
    return SearchResponse(
        search_id=search.id,
        origin=search.origin,
        destination=search.destination,
        departure_date=search.departure_date,
        return_date=search.return_date,
        offer_count=len(offers),
        offers=[_offer_to_out(o) for o in offers],
    )


@router.get("/search/{search_id}/results", response_model=SearchResponse)
async def get_search_results(
    search_id: UUID,
    sort_by: str = Query("price", pattern="^(price|duration|stops)$"),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    search = await session.get(Search, search_id)
    if not search:
        raise HTTPException(404, f"Search {search_id} not found")

    sort_col = {
        "price": FlightOffer.price_usd,
        "duration": FlightOffer.total_duration,
        "stops": FlightOffer.stops,
    }[sort_by]

    stmt = (
        select(FlightOffer)
        .where(FlightOffer.search_id == search_id)
        .order_by(sort_col.asc())
        .limit(limit)
    )
    offers = (await session.execute(stmt)).scalars().all()
    return SearchResponse(
        search_id=search.id,
        origin=search.origin,
        destination=search.destination,
        departure_date=search.departure_date,
        return_date=search.return_date,
        offer_count=len(offers),
        offers=[_offer_to_out(o) for o in offers],
    )
