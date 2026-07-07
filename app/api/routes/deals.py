"""Location resolution + deal-scan endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.booking import BookingLinkOut
from app.api.schemas.deals import (
    AirportHitOut,
    DateBestOut,
    DealScanRequest,
    DealScanResponse,
    OpportunityOut,
    ResolveResponse,
)
from app.db import get_session
from app.services.deals import scan_deals
from app.services.geo import resolve_location

router = APIRouter(prefix="/api/v1", tags=["deals"])


@router.get("/airports/resolve", response_model=ResolveResponse)
async def airports_resolve(
    q: str = Query(..., min_length=1, description="IATA code, city name, or 'lat,lon'"),
    radius_km: float = Query(150.0, ge=0, le=500),
    limit: int = Query(6, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
) -> ResolveResponse:
    """Resolve a free-form location to nearby airports (closest first)."""
    loc = await resolve_location(session, q, radius_km=radius_km, limit=limit)
    return ResolveResponse(
        query=loc.query, kind=loc.kind, label=loc.label,
        airports=[
            AirportHitOut(
                iata_code=h.airport.iata_code, name=h.airport.name,
                city=h.airport.city, country=h.airport.country,
                distance_km=round(h.distance_km, 1),
            )
            for h in loc.airports
        ],
    )


@router.post("/deals/scan", response_model=DealScanResponse)
async def deals_scan(
    body: DealScanRequest, session: AsyncSession = Depends(get_session)
) -> DealScanResponse:
    """Scan a date window × nearby airports for the cheapest days to fly."""
    try:
        result = await scan_deals(
            session,
            origin_query=body.origin,
            destination_query=body.destination,
            date_from=body.date_from,
            date_to=body.date_to,
            trip_length_days=body.trip_length_days,
            cabin_class=body.cabin_class,
            max_searches=body.max_searches,
            include_nearby=body.include_nearby,
            include_hacker_fares=body.include_hacker_fares,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    def _date_best(b) -> DateBestOut:
        return DateBestOut(
            departure_date=b.departure_date, return_date=b.return_date,
            origin=b.origin, destination=b.destination,
            price_usd=b.price_usd, source=b.source, stops=b.stops,
            vs_median_pct=(round(b.vs_median_pct, 1)
                           if b.vs_median_pct is not None else None),
            tier=b.tier,
        )

    return DealScanResponse(
        origin_label=result.origin.label,
        origin_airports=result.origin.codes,
        destination_label=result.destination.label,
        destination_airports=result.destination.codes,
        date_from=result.date_from,
        date_to=result.date_to,
        searches_run=result.searches_run,
        dates_sampled=result.dates_sampled,
        median_price_usd=result.median_price_usd,
        by_date=[_date_best(b) for b in result.by_date],
        best=_date_best(result.best) if result.best else None,
        booking_links=[BookingLinkOut(**vars(link)) for link in result.booking_links],
        opportunities=[
            OpportunityOut(
                strategy=o.candidate.strategy.value,
                price_usd=o.candidate.price_usd,
                savings_usd=o.savings_usd,
                savings_pct=round(o.savings_pct, 1),
                risk_level=o.risk.overall_level.value,
                risk_reasoning=o.risk.reasoning,
                booking_steps=o.booking_steps,
            )
            for o in result.opportunities
        ],
    )
