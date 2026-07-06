"""Booking-handoff endpoints — from a priced offer to a place to buy it."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.booking import BookingLinkOut, BookingLinksResponse
from app.db import get_session
from app.models import Airline, FlightOffer, Search
from app.services.booking import build_offer_links

router = APIRouter(prefix="/api/v1/offers", tags=["booking"])


@router.get("/{offer_id}/booking", response_model=BookingLinksResponse)
async def offer_booking_links(
    offer_id: UUID, session: AsyncSession = Depends(get_session)
) -> BookingLinksResponse:
    offer = await session.get(FlightOffer, offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="offer not found")

    carrier = (offer.segments or [{}])[0].get("carrier", "")
    airline = await session.get(Airline, carrier) if carrier else None
    search = (
        await session.get(Search, offer.search_id) if offer.search_id else None
    )

    links = build_offer_links(offer, airline=airline, search=search)
    route = (
        f"{search.origin}→{search.destination}" if search
        else " → ".join(
            [offer.segments[0]["origin"], offer.segments[-1]["destination"]]
        ) if offer.segments else "unknown route"
    )
    return BookingLinksResponse(
        context=f"{route} via {offer.source} at ${float(offer.price_usd):,.0f}",
        price_usd=offer.price_usd,
        links=[BookingLinkOut(**vars(link)) for link in links],
    )
