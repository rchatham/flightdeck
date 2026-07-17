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
    return_origin: str | None = Field(
        default=None, min_length=3, max_length=3,
        description="Open-jaw: return leg departs here instead of `destination`",
    )
    return_destination: str | None = Field(
        default=None, min_length=3, max_length=3,
        description="Open-jaw: return leg arrives here instead of `origin`",
    )
    cabin_class: CabinClass = "economy"
    target_price_usd: Decimal | None = Field(default=None, ge=0)

    @field_validator("origin", "destination", "return_origin", "return_destination")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class WatchUpdate(BaseModel):
    departure_date: date | None = None
    return_date: date | None = None
    return_origin: str | None = Field(default=None, min_length=3, max_length=3)
    return_destination: str | None = Field(default=None, min_length=3, max_length=3)
    cabin_class: CabinClass | None = None
    target_price_usd: Decimal | None = Field(default=None, ge=0)
    active: bool | None = None

    @field_validator("return_origin", "return_destination")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class WatchOut(BaseModel):
    id: UUID
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    return_origin: str | None
    return_destination: str | None
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
