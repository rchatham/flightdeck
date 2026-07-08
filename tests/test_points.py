"""Tests for points-redemption estimation (pure functions — no DB)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.points import (
    DEFAULT_CPP,
    PROGRAM_VALUATIONS_CPP,
    ProgramBalance,
    cents_per_point_for,
    estimate_redemptions,
    points_needed,
)


def test_points_needed_basic_math():
    # $750 at 2.0 cents/point = 75000 cents / 2.0 = 37500 points exactly.
    assert points_needed(Decimal("750"), 2.0) == 37500


def test_points_needed_rounds_up():
    # $10.01 at 2.0 cents/point = 500.5 -> must round UP (partial points don't exist).
    assert points_needed(Decimal("10.01"), 2.0) == 501


def test_points_needed_zero_price():
    assert points_needed(Decimal("0"), 2.0) == 0


def test_points_needed_rejects_non_positive_valuation():
    with pytest.raises(ValueError):
        points_needed(Decimal("100"), 0)
    with pytest.raises(ValueError):
        points_needed(Decimal("100"), -1.0)


def test_cents_per_point_known_program():
    expected = PROGRAM_VALUATIONS_CPP["Chase Ultimate Rewards"]
    assert cents_per_point_for("Chase Ultimate Rewards") == expected


def test_cents_per_point_unknown_program_falls_back_to_default():
    assert cents_per_point_for("Some Random Airline Club") == DEFAULT_CPP


def test_estimate_redemptions_sufficient_balance_ranks_first():
    programs = [
        # sufficient, cheaper CPP -> more points needed
        ProgramBalance("Citi ThankYou Rewards", balance=100_000),
        ProgramBalance("Chase Ultimate Rewards", balance=0),  # insufficient
    ]
    estimates = estimate_redemptions(Decimal("750"), programs)
    assert estimates[0].program_name == "Citi ThankYou Rewards"
    assert estimates[0].sufficient is True
    assert estimates[1].program_name == "Chase Ultimate Rewards"
    assert estimates[1].sufficient is False


def test_estimate_redemptions_within_sufficient_group_sorts_by_points_needed():
    programs = [
        ProgramBalance("Citi ThankYou Rewards", balance=100_000),   # 1.7 cpp -> more points needed
        ProgramBalance("Chase Ultimate Rewards", balance=100_000),  # 2.0 cpp -> fewer points needed
    ]
    estimates = estimate_redemptions(Decimal("750"), programs)
    names = [e.program_name for e in estimates]
    assert names == ["Chase Ultimate Rewards", "Citi ThankYou Rewards"]
    assert estimates[0].points_needed < estimates[1].points_needed


def test_estimate_redemptions_shortfall_is_none_when_sufficient():
    programs = [ProgramBalance("Chase Ultimate Rewards", balance=100_000)]
    est = estimate_redemptions(Decimal("750"), programs)[0]
    assert est.sufficient is True
    assert est.shortfall is None


def test_estimate_redemptions_shortfall_is_exact_gap():
    programs = [ProgramBalance("Chase Ultimate Rewards", balance=10_000)]
    est = estimate_redemptions(Decimal("750"), programs)[0]
    assert est.sufficient is False
    assert est.shortfall == est.points_needed - 10_000


def test_estimate_redemptions_empty_programs():
    assert estimate_redemptions(Decimal("750"), []) == []


def test_estimate_redemptions_unknown_program_uses_default_valuation():
    programs = [ProgramBalance("Random New Card", balance=0)]
    est = estimate_redemptions(Decimal("100"), programs)[0]
    assert est.cents_per_point == DEFAULT_CPP
