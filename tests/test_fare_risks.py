"""Tests for `score_hidden_fare_risk` — Hook 3 user contribution.

The default stub returns MEDIUM for everything. These tests pass against the
default. As you add per-strategy logic (HIDDEN_CITY differs from SPLIT_TICKET,
cross-carrier matters, has_checked_bag matters, etc.), the marked tests turn
green.

Remove xfail markers as you implement each rule.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.integrations.types import Segment
from app.services.fare_risks import (
    FLAG_BAG_LOSS,
    FLAG_NO_INTERLINE_PROTECTION,
    FLAG_PNR_CANCEL,
    FareStrategy,
    HiddenFareCandidate,
    RiskAssessment,
    RiskFlag,
    RiskLevel,
    score_hidden_fare_risk,
)


def _seg(carrier="UA", origin="SFO", destination="NRT", flight_no="100",
         hour=11) -> Segment:
    depart = datetime(2026, 6, 15, hour, 0)
    arrive = depart + timedelta(hours=11, minutes=30)
    return Segment(
        carrier=carrier, flight_no=flight_no, origin=origin, destination=destination,
        depart_at=depart, arrive_at=arrive, duration=timedelta(hours=11, minutes=30),
    )


def hidden_city_candidate(
    *,
    has_return: bool = False,
    has_checked_bag: bool = False,
    intermediate: str = "NRT",
    final: str = "TPE",
) -> HiddenFareCandidate:
    leg1 = _seg(origin="SFO", destination=intermediate)
    leg2 = _seg(origin=intermediate, destination=final, hour=22)
    return HiddenFareCandidate(
        strategy=FareStrategy.HIDDEN_CITY,
        price_usd=Decimal("750"),
        real_destination=intermediate,
        final_destination=final,
        useful_segments=[leg1],
        full_segments=[leg1, leg2],
        has_return=has_return,
        has_checked_bag=has_checked_bag,
    )


def split_ticket_candidate(*, cross_carrier: bool = False) -> HiddenFareCandidate:
    out = _seg(carrier="UA", origin="SFO", destination="NRT")
    inb = _seg(carrier="DL" if cross_carrier else "UA", origin="NRT", destination="SFO", hour=18)
    return HiddenFareCandidate(
        strategy=FareStrategy.SPLIT_TICKET,
        price_usd=Decimal("1100"),
        real_destination="NRT",
        final_destination="NRT",
        useful_segments=[out, inb],
        full_segments=[out, inb],
        has_return=True,
        has_checked_bag=True,
        cross_carrier=cross_carrier,
    )


# --- Default-stub-passes tests -----------------------------------------------

def test_returns_assessment_with_overall_level():
    rec = score_hidden_fare_risk(hidden_city_candidate())
    assert isinstance(rec, RiskAssessment)
    assert rec.overall_level in {RiskLevel.LOW, RiskLevel.MEDIUM,
                                 RiskLevel.HIGH, RiskLevel.EXTREME,
                                 RiskLevel.DISQUALIFIED}


def test_returns_at_least_one_flag():
    rec = score_hidden_fare_risk(hidden_city_candidate())
    assert len(rec.flags) >= 1


def test_each_flag_has_required_fields():
    rec = score_hidden_fare_risk(hidden_city_candidate())
    for f in rec.flags:
        assert isinstance(f, RiskFlag)
        assert f.code
        assert f.description


# --- Behavior the user will implement ----------------------------------------


@pytest.mark.xfail(reason="Implement HIDDEN_CITY+round-trip disqualification", strict=False)
def test_hidden_city_with_round_trip_is_disqualified():
    """Hidden-city + round-trip is structurally broken — return is auto-cancelled."""
    cand = hidden_city_candidate(has_return=True)
    rec = score_hidden_fare_risk(cand)
    assert rec.overall_level == RiskLevel.DISQUALIFIED


@pytest.mark.xfail(reason="Implement bag-check escalation for hidden_city", strict=False)
def test_hidden_city_with_checked_bag_is_extreme():
    """Hidden-city + checked bag = lost luggage. Bump severity."""
    cand = hidden_city_candidate(has_checked_bag=True)
    rec = score_hidden_fare_risk(cand)
    assert rec.overall_level == RiskLevel.EXTREME
    assert any(f.code == "bag_loss" for f in rec.flags)


@pytest.mark.xfail(reason="Implement default hidden_city HIGH severity", strict=False)
def test_hidden_city_carry_on_one_way_is_high():
    """Carry-on, one-way hidden-city is HIGH severity (skiplagging is never LOW)."""
    cand = hidden_city_candidate(has_checked_bag=False, has_return=False)
    rec = score_hidden_fare_risk(cand)
    assert rec.overall_level in (RiskLevel.HIGH, RiskLevel.MEDIUM)
    flag_codes = {f.code for f in rec.flags}
    assert "pnr_cancel" in flag_codes or "loyalty_closure" in flag_codes


def test_split_ticket_same_carrier_is_low():
    """Same-carrier split is barely riskier than booking round-trip."""
    cand = split_ticket_candidate(cross_carrier=False)
    rec = score_hidden_fare_risk(cand)
    assert rec.overall_level in (RiskLevel.LOW, RiskLevel.MEDIUM)


@pytest.mark.xfail(reason="Implement split-ticket cross-carrier HIGH", strict=False)
def test_split_ticket_cross_carrier_is_high():
    """Cross-carrier split has no interline protection if leg 1 fails."""
    cand = split_ticket_candidate(cross_carrier=True)
    rec = score_hidden_fare_risk(cand)
    assert rec.overall_level == RiskLevel.HIGH
    assert any(f.code == "no_interline" for f in rec.flags)


# --- Sanity ------------------------------------------------------------------


def test_predefined_flags_have_distinct_codes():
    """The shared flag constants should not collide on `code`."""
    flags = [FLAG_BAG_LOSS, FLAG_PNR_CANCEL, FLAG_NO_INTERLINE_PROTECTION]
    codes = [f.code for f in flags]
    assert len(codes) == len(set(codes))
