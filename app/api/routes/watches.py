"""Price-watch endpoints — the tracking half of FlightDeck."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.booking import BookingLinkOut, BookingLinksResponse
from app.api.schemas.watches import (
    AlertListResponse,
    AlertOut,
    CheckResponse,
    WatchCreate,
    WatchListResponse,
    WatchOut,
    WatchUpdate,
)
from app.db import get_session
from app.models import PriceAlert, PriceWatch
from app.services.booking import build_route_links
from app.services.watches import check_watch

router = APIRouter(prefix="/api/v1/watches", tags=["watches"])


@router.post("", response_model=WatchOut, status_code=201)
async def create_watch(
    body: WatchCreate, session: AsyncSession = Depends(get_session)
) -> WatchOut:
    watch = PriceWatch(
        origin=body.origin,
        destination=body.destination,
        departure_date=body.departure_date,
        return_date=body.return_date,
        return_origin=body.return_origin,
        return_destination=body.return_destination,
        cabin_class=body.cabin_class,
        target_price_usd=body.target_price_usd,
    )
    session.add(watch)
    await session.commit()
    await session.refresh(watch)
    return WatchOut.model_validate(watch)


@router.get("", response_model=WatchListResponse)
async def list_watches(
    include_inactive: bool = Query(False),
    session: AsyncSession = Depends(get_session),
) -> WatchListResponse:
    stmt = select(PriceWatch).order_by(PriceWatch.departure_date)
    if not include_inactive:
        stmt = stmt.where(PriceWatch.active.is_(True))
    watches = (await session.execute(stmt)).scalars().all()
    return WatchListResponse(
        count=len(watches),
        watches=[WatchOut.model_validate(w) for w in watches],
    )


# NOTE: declared before /{watch_id} so 'alerts' isn't parsed as a UUID.
@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    include_acknowledged: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> AlertListResponse:
    stmt = select(PriceAlert).order_by(PriceAlert.created_at.desc()).limit(limit)
    if not include_acknowledged:
        stmt = stmt.where(PriceAlert.acknowledged.is_(False))
    alerts = (await session.execute(stmt)).scalars().all()
    return AlertListResponse(
        count=len(alerts),
        alerts=[AlertOut.model_validate(a) for a in alerts],
    )


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: UUID, session: AsyncSession = Depends(get_session)
) -> AlertOut:
    alert = await session.get(PriceAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    alert.acknowledged = True
    await session.commit()
    return AlertOut.model_validate(alert)


@router.get("/{watch_id}", response_model=WatchOut)
async def get_watch(
    watch_id: UUID, session: AsyncSession = Depends(get_session)
) -> WatchOut:
    watch = await session.get(PriceWatch, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="watch not found")
    return WatchOut.model_validate(watch)


@router.patch("/{watch_id}", response_model=WatchOut)
async def update_watch(
    watch_id: UUID, body: WatchUpdate, session: AsyncSession = Depends(get_session)
) -> WatchOut:
    """Edit a watch in place — target price, dates, cabin, or active state.

    Origin/destination are immutable; that's a different trip, not an edit.
    Keeps alert/price history tied to the same watch id instead of losing it
    to a delete-and-recreate.
    """
    watch = await session.get(PriceWatch, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="watch not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(watch, field, value)
    await session.commit()
    await session.refresh(watch)
    return WatchOut.model_validate(watch)


@router.delete("/{watch_id}", status_code=204)
async def delete_watch(
    watch_id: UUID, session: AsyncSession = Depends(get_session)
) -> None:
    watch = await session.get(PriceWatch, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="watch not found")
    await session.delete(watch)
    await session.commit()


@router.get("/{watch_id}/booking", response_model=BookingLinksResponse)
async def watch_booking_links(
    watch_id: UUID, session: AsyncSession = Depends(get_session)
) -> BookingLinksResponse:
    """Where to book the watched trip — e.g. after an alert fires."""
    watch = await session.get(PriceWatch, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="watch not found")
    links = build_route_links(
        watch.origin, watch.destination, watch.departure_date, watch.return_date
    )
    context = f"{watch.origin}→{watch.destination} on {watch.departure_date.isoformat()}"
    if watch.last_price_usd is not None:
        context += f" (last seen ${float(watch.last_price_usd):,.0f})"
    return BookingLinksResponse(
        context=context,
        price_usd=watch.last_price_usd,
        links=[BookingLinkOut(**vars(link)) for link in links],
    )


@router.post("/{watch_id}/check", response_model=CheckResponse)
async def force_check(
    watch_id: UUID, session: AsyncSession = Depends(get_session)
) -> CheckResponse:
    """Run a live check now instead of waiting for the next scheduled run."""
    watch = await session.get(PriceWatch, watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="watch not found")
    outcome = await check_watch(session, watch)
    await session.refresh(watch)
    return CheckResponse(
        watch=WatchOut.model_validate(watch),
        offers_found=outcome.offers_found,
        cheapest_price_usd=outcome.cheapest_price_usd,
        alert_fired=outcome.alert is not None,
        alert=AlertOut.model_validate(outcome.alert) if outcome.alert else None,
        deactivated=outcome.deactivated,
    )
