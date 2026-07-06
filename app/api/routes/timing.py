"""Timing analyzer endpoints — Hook 2's surface."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.timing import AnalyzeResponse, HistoryResponse, PricePointOut
from app.db import get_session
from app.services.timing_analyzer import analyze_route, get_history

router = APIRouter(prefix="/api/v1/timing", tags=["timing"])


@router.get("/analyze", response_model=AnalyzeResponse)
async def analyze(
    origin: str = Query(..., min_length=3, max_length=3),
    destination: str = Query(..., min_length=3, max_length=3),
    departure_date: date = Query(...),
    current_price: Decimal | None = Query(None, ge=0),
    lookback_days: int = Query(180, ge=7, le=730),
    session: AsyncSession = Depends(get_session),
) -> AnalyzeResponse:
    rec = await analyze_route(
        session,
        origin=origin.upper(),
        destination=destination.upper(),
        departure_date=departure_date,
        current_price=current_price,
        lookback_days=lookback_days,
    )
    days_until = (departure_date - date.today()).days
    return AnalyzeResponse(
        route=f"{origin.upper()}-{destination.upper()}",
        departure_date=departure_date,
        days_until_departure=days_until,
        verdict=rec.verdict.value,
        confidence=rec.confidence,
        reasoning=rec.reasoning,
        sample_count=rec.sample_count,
        median_price=rec.median_price,
        current_pct_above_median=rec.current_pct_above_median,
    )


@router.get("/history", response_model=HistoryResponse)
async def history(
    route_key: str = Query(..., description="e.g. 'SFO-NRT' or 'SFO-NRT:2026-06-15'"),
    lookback_days: int = Query(180, ge=7, le=730),
    session: AsyncSession = Depends(get_session),
) -> HistoryResponse:
    rows = await get_history(session, route_key, lookback_days=lookback_days)
    points = [
        PricePointOut(
            recorded_at=r.recorded_at,
            price_usd=r.price_usd,
            days_until_departure=r.days_until_departure,
        )
        for r in rows
    ]
    return HistoryResponse(route_key=route_key, point_count=len(points), points=points)
