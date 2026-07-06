"""Pydantic schemas for the timing-analyzer endpoints."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class AnalyzeResponse(BaseModel):
    route: str
    departure_date: date
    days_until_departure: int
    verdict: str
    confidence: float
    reasoning: str
    sample_count: int
    median_price: Decimal | None
    current_pct_above_median: float | None


class PricePointOut(BaseModel):
    recorded_at: datetime
    price_usd: Decimal
    days_until_departure: int | None


class HistoryResponse(BaseModel):
    route_key: str
    point_count: int
    points: list[PricePointOut]
