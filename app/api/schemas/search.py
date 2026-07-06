"""Pydantic request/response schemas for the search endpoint."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

CabinClass = Literal["economy", "premium_economy", "business", "first"]


class SearchRequest(BaseModel):
    origin: str = Field(min_length=3, max_length=3, description="Origin IATA code")
    destination: str = Field(min_length=3, max_length=3, description="Destination IATA code")
    departure_date: date
    return_date: date | None = None
    flex_days: int = Field(default=0, ge=0, le=7, description="±N days flexibility around dates")
    passengers: int = Field(default=1, ge=1, le=9)
    cabin_class: CabinClass = "economy"
    include_nearby: bool = True
    max_stops: int | None = Field(default=None, ge=0, le=3)

    @field_validator("origin", "destination")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class SegmentOut(BaseModel):
    carrier: str
    flight_no: str
    origin: str
    destination: str
    depart_at: datetime
    arrive_at: datetime
    duration: timedelta
    cabin: str


class OfferOut(BaseModel):
    id: UUID
    source: str
    price_usd: Decimal
    currency: str
    total_duration: timedelta | None
    stops: int
    segments: list[SegmentOut]
    fare_type: str
    booking_url: str | None
    deep_link: str | None


class SearchResponse(BaseModel):
    search_id: UUID
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    offer_count: int
    offers: list[OfferOut]
