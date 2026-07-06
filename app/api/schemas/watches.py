"""Pydantic schemas for price watches and alerts."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.api.schemas.search import CabinClass


class WatchCreate(BaseModel):
    origin: str = Field(min_length=3, max_length=3, description="Origin IATA code")
    destination: str = Field(min_length=3, max_length=3, description="Destination IATA code")
    departure_date: date
    return_date: date | None = None
    cabin_class: CabinClass = "economy"
    target_price_usd: Decimal | None = Field(default=None, ge=0)

    @field_validator("origin", "destination")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class WatchOut(BaseModel):
    id: UUID
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    cabin_class: str
    target_price_usd: Decimal | None
    active: bool
    last_checked_at: datetime | None
    last_price_usd: Decimal | None
    lowest_seen_usd: Decimal | None
    last_alerted_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class WatchListResponse(BaseModel):
    count: int
    watches: list[WatchOut]


class AlertOut(BaseModel):
    id: UUID
    watch_id: UUID
    kind: str
    price_usd: Decimal
    previous_price_usd: Decimal | None
    message: str
    acknowledged: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    count: int
    alerts: list[AlertOut]


class CheckResponse(BaseModel):
    watch: WatchOut
    offers_found: int
    cheapest_price_usd: Decimal | None
    alert_fired: bool
    alert: AlertOut | None
    deactivated: bool
