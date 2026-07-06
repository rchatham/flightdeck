"""Pydantic schemas for booking-handoff endpoints."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class BookingLinkOut(BaseModel):
    kind: str
    label: str
    url: str
    note: str


class BookingLinksResponse(BaseModel):
    context: str                     # human summary of what's being booked
    price_usd: Decimal | None = None
    links: list[BookingLinkOut]
