"""Pydantic schemas for hidden-fare discovery."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field


class HiddenFareRequest(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    departure_date: date
    return_date: date | None = None
    passengers: int = Field(default=1, ge=1, le=9)
    cabin_class: str = "economy"
    strategies: list[str] = Field(default_factory=lambda: ["hidden_city", "split_ticket"])
    has_checked_bag: bool = False


class SegmentOut(BaseModel):
    carrier: str
    flight_no: str
    origin: str
    destination: str
    depart_at: datetime
    arrive_at: datetime
    duration: timedelta


class FlagOut(BaseModel):
    code: str
    severity: str
    description: str


class OpportunityOut(BaseModel):
    strategy: str
    overall_risk: str
    risk_reasoning: str
    risk_flags: list[FlagOut]
    price_usd: Decimal
    direct_price_usd: Decimal
    savings_usd: Decimal
    savings_pct: float
    real_destination: str
    final_destination: str
    useful_segments: list[SegmentOut]
    booking_steps: list[str]
    booking_url: str | None


class HiddenFareResponse(BaseModel):
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    direct_price_usd: Decimal | None
    opportunity_count: int
    opportunities: list[OpportunityOut]
