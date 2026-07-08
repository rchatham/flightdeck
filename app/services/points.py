"""Points & rewards — redemption-value estimates for transferable currencies.

The seeded `points_programs` table (data/transfer_partners.json) tracks the
user's balance per program and each program's airline transfer partners.
This module answers the question travel-hackers actually ask: "should I pay
cash or redeem points for this fare, and which program should I use?"

Valuations below are rough, hand-maintained cents-per-point estimates in the
spirit of community consensus (e.g. The Points Guy's annual valuations) —
they drift constantly and vary by redemption. Treat them as a starting
point: update PROGRAM_VALUATIONS_CPP as your own redemption experience
differs, or add entries for programs beyond the seeded four.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import ceil

PROGRAM_VALUATIONS_CPP: dict[str, float] = {
    "Chase Ultimate Rewards": 2.0,
    "American Express Membership Rewards": 2.0,
    "Citi ThankYou Rewards": 1.7,
    "Capital One Venture Miles": 1.85,
}
DEFAULT_CPP = 1.5  # fallback for programs not in the table above


def cents_per_point_for(program_name: str) -> float:
    return PROGRAM_VALUATIONS_CPP.get(program_name, DEFAULT_CPP)


def points_needed(cash_price_usd: Decimal, cents_per_point: float) -> int:
    """How many points redeem for `cash_price_usd` at `cents_per_point` value."""
    if cents_per_point <= 0:
        raise ValueError("cents_per_point must be positive")
    cents = float(cash_price_usd) * 100
    return ceil(cents / cents_per_point)


@dataclass
class ProgramBalance:
    """Minimal shape estimate_redemptions needs — decoupled from the ORM model
    so the estimator stays a pure function testable without a database."""

    program_name: str
    balance: int


@dataclass
class RedemptionEstimate:
    program_name: str
    cents_per_point: float
    points_needed: int
    balance: int
    sufficient: bool
    shortfall: int | None  # None when sufficient


def estimate_redemptions(
    cash_price_usd: Decimal, programs: list[ProgramBalance]
) -> list[RedemptionEstimate]:
    """Points needed per program for `cash_price_usd`.

    Sorted with sufficient-balance programs first (so "what can I book right
    now" is obvious at a glance), cheapest-in-points-terms within each group.
    """
    estimates = [
        _estimate_one(cash_price_usd, p) for p in programs
    ]
    estimates.sort(key=lambda e: (not e.sufficient, e.points_needed))
    return estimates


def _estimate_one(cash_price_usd: Decimal, program: ProgramBalance) -> RedemptionEstimate:
    cpp = cents_per_point_for(program.program_name)
    needed = points_needed(cash_price_usd, cpp)
    sufficient = program.balance >= needed
    return RedemptionEstimate(
        program_name=program.program_name, cents_per_point=cpp,
        points_needed=needed, balance=program.balance,
        sufficient=sufficient, shortfall=None if sufficient else needed - program.balance,
    )
