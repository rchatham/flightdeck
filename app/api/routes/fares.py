"""Hidden-fare discovery endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas.fares import (
    FlagOut,
    HiddenFareRequest,
    HiddenFareResponse,
    OpportunityOut,
    SegmentOut,
)
from app.api.schemas.search import SearchRequest
from app.services.fare_discovery import discover_opportunities
from app.services.fare_risks import FareStrategy

router = APIRouter(prefix="/api/v1/fares", tags=["fares"])


@router.post("/hidden", response_model=HiddenFareResponse)
async def hidden_fares(req: HiddenFareRequest) -> HiddenFareResponse:
    # Map strategy strings to enum
    try:
        strategies = [FareStrategy(s) for s in req.strategies]
    except ValueError as e:
        raise HTTPException(400, f"Unknown strategy: {e}")

    search_req = SearchRequest(
        origin=req.origin,
        destination=req.destination,
        departure_date=req.departure_date,
        return_date=req.return_date,
        passengers=req.passengers,
        cabin_class=req.cabin_class,
        include_nearby=False,
    )
    opportunities = await discover_opportunities(search_req, strategies)
    direct_price = opportunities[0].direct_price_usd if opportunities else None

    out = []
    for opp in opportunities:
        out.append(
            OpportunityOut(
                strategy=opp.candidate.strategy.value,
                overall_risk=opp.risk.overall_level.value,
                risk_reasoning=opp.risk.reasoning,
                risk_flags=[
                    FlagOut(code=f.code, severity=f.severity.value, description=f.description)
                    for f in opp.risk.flags
                ],
                price_usd=opp.candidate.price_usd,
                direct_price_usd=opp.direct_price_usd,
                savings_usd=opp.savings_usd,
                savings_pct=opp.savings_pct,
                real_destination=opp.candidate.real_destination,
                final_destination=opp.candidate.final_destination,
                useful_segments=[
                    SegmentOut(
                        carrier=s.carrier, flight_no=s.flight_no,
                        origin=s.origin, destination=s.destination,
                        depart_at=s.depart_at, arrive_at=s.arrive_at,
                        duration=s.duration,
                    )
                    for s in opp.candidate.useful_segments
                ],
                booking_steps=opp.booking_steps,
                booking_url=opp.candidate.booking_url,
            )
        )

    return HiddenFareResponse(
        origin=req.origin.upper(),
        destination=req.destination.upper(),
        departure_date=req.departure_date,
        return_date=req.return_date,
        direct_price_usd=direct_price,
        opportunity_count=len(out),
        opportunities=out,
    )
