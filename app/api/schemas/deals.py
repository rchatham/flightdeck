"""Pydantic schemas for location resolution and deal scanning."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.api.schemas.booking import BookingLinkOut
from app.api.schemas.search import CabinClass


# --- Airports / location resolution ------------------------------------------


class AirportHitOut(BaseModel):
    iata_code: str
    name: str
    city: str
    country: str
    distance_km: float


class ResolveResponse(BaseModel):
    query: str
    kind: str                      # iata | latlon | name
    label: str
    airports: list[AirportHitOut]


# --- Deal scan -----------------------------------------------------------------


class DealScanRequest(BaseModel):
    origin: str = Field(min_length=1, description="IATA code, city name, or 'lat,lon'")
    destination: str = Field(min_length=1, description="IATA code, city name, or 'lat,lon'")
    date_from: date
    date_to: date
    trip_length_days: int | None = Field(default=None, ge=1, le=90,
                                         description="Round-trip length; omit for one-way")
    cabin_class: CabinClass = "economy"
    max_searches: int = Field(default=12, ge=1, le=40,
                              description="Cap on live fan-outs (each hits every source)")
    include_nearby: bool = True
    include_hacker_fares: bool = False


class DateBestOut(BaseModel):
    departure_date: date
    return_date: date | None
    origin: str
    destination: str
    price_usd: Decimal
    source: str
    stops: int
    vs_median_pct: float | None
    tier: str | None               # DEAL | GOOD | null


class OpportunityOut(BaseModel):
    strategy: str
    price_usd: Decimal
    savings_usd: Decimal
    savings_pct: float
    risk_level: str
    risk_reasoning: str
    booking_steps: list[str]


class DealScanResponse(BaseModel):
    origin_label: str
    origin_airports: list[str]
    destination_label: str
    destination_airports: list[str]
    date_from: date
    date_to: date
    searches_run: int
    dates_sampled: int
    median_price_usd: Decimal | None
    by_date: list[DateBestOut]
    best: DateBestOut | None
    booking_links: list[BookingLinkOut]
    opportunities: list[OpportunityOut]
