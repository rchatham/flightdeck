"""Pydantic schemas for points-program balances and redemption estimates."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class TransferPartnerOut(BaseModel):
    airline: str
    iata: str
    ratio: str
    bonus_pct: float = 0


class ProgramOut(BaseModel):
    id: UUID
    program_name: str
    card_name: str | None
    balance: int
    transfer_partners: list[TransferPartnerOut]
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProgramListResponse(BaseModel):
    count: int
    programs: list[ProgramOut]


class BalanceUpdate(BaseModel):
    balance: int = Field(ge=0)


class RedemptionEstimateRequest(BaseModel):
    cash_price_usd: Decimal = Field(ge=0)


class RedemptionEstimateOut(BaseModel):
    program_name: str
    cents_per_point: float
    points_needed: int
    balance: int
    sufficient: bool
    shortfall: int | None


class RedemptionEstimateResponse(BaseModel):
    cash_price_usd: Decimal
    estimates: list[RedemptionEstimateOut]
