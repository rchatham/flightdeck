"""Points-program balance and redemption-estimate endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.points import (
    BalanceUpdate,
    ProgramListResponse,
    ProgramOut,
    RedemptionEstimateOut,
    RedemptionEstimateRequest,
    RedemptionEstimateResponse,
    TransferPartnerOut,
)
from app.db import get_session
from app.models import PointsProgram
from app.services.points import ProgramBalance, estimate_redemptions

router = APIRouter(prefix="/api/v1/points", tags=["points"])


def _to_program_out(row: PointsProgram) -> ProgramOut:
    return ProgramOut(
        id=row.id, program_name=row.program_name, card_name=row.card_name,
        balance=row.balance,
        transfer_partners=[TransferPartnerOut(**p) for p in (row.transfer_partners or [])],
        updated_at=row.updated_at,
    )


@router.get("", response_model=ProgramListResponse)
async def list_programs(session: AsyncSession = Depends(get_session)) -> ProgramListResponse:
    rows = (
        await session.execute(select(PointsProgram).order_by(PointsProgram.program_name))
    ).scalars().all()
    return ProgramListResponse(count=len(rows), programs=[_to_program_out(r) for r in rows])


@router.get("/{program_id}", response_model=ProgramOut)
async def get_program(
    program_id: UUID, session: AsyncSession = Depends(get_session)
) -> ProgramOut:
    row = await session.get(PointsProgram, program_id)
    if row is None:
        raise HTTPException(status_code=404, detail="points program not found")
    return _to_program_out(row)


@router.patch("/{program_id}", response_model=ProgramOut)
async def update_balance(
    program_id: UUID, body: BalanceUpdate, session: AsyncSession = Depends(get_session)
) -> ProgramOut:
    row = await session.get(PointsProgram, program_id)
    if row is None:
        raise HTTPException(status_code=404, detail="points program not found")
    row.balance = body.balance
    await session.commit()
    await session.refresh(row)
    return _to_program_out(row)


@router.post("/estimate", response_model=RedemptionEstimateResponse)
async def estimate(
    body: RedemptionEstimateRequest, session: AsyncSession = Depends(get_session)
) -> RedemptionEstimateResponse:
    """Points needed per program for a cash price — sufficient balances first,
    cheapest-in-points-terms within each group."""
    rows = (await session.execute(select(PointsProgram))).scalars().all()
    balances = [ProgramBalance(program_name=r.program_name, balance=r.balance) for r in rows]
    estimates = estimate_redemptions(body.cash_price_usd, balances)
    return RedemptionEstimateResponse(
        cash_price_usd=body.cash_price_usd,
        estimates=[
            RedemptionEstimateOut(
                program_name=e.program_name, cents_per_point=e.cents_per_point,
                points_needed=e.points_needed, balance=e.balance,
                sufficient=e.sufficient, shortfall=e.shortfall,
            )
            for e in estimates
        ],
    )
