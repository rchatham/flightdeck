"""Tests for `score_offer` — the Hook 1 user contribution.

Scoring weights (from owner survey):
  • Price: linear USD
  • Duration: $5 / hour
  • Stops: 50 × stops² (nonstop adds an extra −$25 bonus)
  • First takeoff before 7am OR at/after 10pm: +$30
  • Last landing at/after 11pm: +$40
  • Last landing before 6am: +$30
  • Preferred carrier: −$30
  • Avoid carrier: +$60
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.integrations.types import NormalizedOffer, Segment
from app.services.ranking import (
    RankingPreferences,
    primary_carrier,
    relative_price_pct_above_cheapest,
    score_offer,
)


def make_offer(
    *,
    price: float,
    duration_hours: float = 11.5,
    stops: int = 0,
    carrier: str = "UA",
    depart_hour: int = 11,
    arrive_hour: int | None = None,
    source_id: str = "x",
) -> NormalizedOffer:
    """Factory for test offers — single segment by default, override as needed."""
    depart = datetime(2026, 6, 15, depart_hour, 0)
    arrive = depart + timedelta(hours=duration_hours)
    if arrive_hour is not None:
        # Override arrival to a specific hour-of-day (same calendar day for simplicity)
        arrive = datetime(2026, 6, 15, arrive_hour, 0)
        if arrive <= depart:
            arrive = arrive + timedelta(days=1)
    return NormalizedOffer(
        source="amadeus",
        source_id=source_id,
        price_usd=Decimal(str(price)),
        currency="USD",
        total_duration=timedelta(hours=duration_hours),
        stops=stops,
        segments=[
            Segment(
                carrier=carrier,
                flight_no="100",
                origin="SFO",
                destination="NRT",
                depart_at=depart,
                arrive_at=arrive,
                duration=timedelta(hours=duration_hours),
            )
        ],
    )


# A neutral preferences fixture: a 11am-departing, 10:30pm-arriving same-day flight
# falls inside all default thresholds, so timing_penalty is 0.
NEUTRAL_PREFS = RankingPreferences()


# --- Sanity checks -----------------------------------------------------------

def test_lower_price_scores_better():
    cheap = make_offer(price=500)
    expensive = make_offer(price=900, source_id="exp")
    assert score_offer(cheap, NEUTRAL_PREFS).score < score_offer(expensive, NEUTRAL_PREFS).score


def test_score_returns_breakdown():
    offer = make_offer(price=600)
    scored = score_offer(offer, NEUTRAL_PREFS)
    expected_keys = {"price", "duration", "stops", "nonstop_bonus", "timing", "carrier"}
    assert expected_keys.issubset(scored.breakdown.keys())


# --- Duration weighting ------------------------------------------------------

def test_shorter_duration_breaks_price_tie():
    """At equal price, shorter trip wins by $5/hour."""
    fast = make_offer(price=600, duration_hours=11)
    slow = make_offer(price=600, duration_hours=18, source_id="slow")
    assert score_offer(fast, NEUTRAL_PREFS).score < score_offer(slow, NEUTRAL_PREFS).score


def test_duration_weight_is_5_per_hour():
    fast = make_offer(price=600, duration_hours=10)
    slow = make_offer(price=600, duration_hours=20, source_id="slow")
    diff = score_offer(slow, NEUTRAL_PREFS).score - score_offer(fast, NEUTRAL_PREFS).score
    assert diff == pytest.approx(50.0)  # 10 extra hours × $5


# --- Stops penalty -----------------------------------------------------------

def test_nonstop_beats_one_stop_at_equal_price():
    """Nonstop should beat 1-stop by stops_penalty + nonstop_bonus = 50 + 25 = $75."""
    nonstop = make_offer(price=600, stops=0, duration_hours=11.5)
    one_stop = make_offer(price=600, stops=1, duration_hours=11.5, source_id="1s")
    diff = score_offer(one_stop, NEUTRAL_PREFS).score - score_offer(nonstop, NEUTRAL_PREFS).score
    assert diff == pytest.approx(75.0)


def test_two_stops_more_painful_than_two_one_stops():
    """Penalty is quadratic: 1+1 stops = $100, but 2 stops = $200. Confirm."""
    one_stop = make_offer(price=600, stops=1, duration_hours=11.5)
    two_stops = make_offer(price=600, stops=2, duration_hours=11.5, source_id="2s")
    one_score = score_offer(one_stop, NEUTRAL_PREFS).score
    two_score = score_offer(two_stops, NEUTRAL_PREFS).score
    assert (two_score - one_score) == pytest.approx(150.0)  # 200 - 50 = 150


# --- Carrier preferences -----------------------------------------------------

def test_preferred_carrier_gets_30_bonus():
    preferred = make_offer(price=600, carrier="UA")
    other = make_offer(price=600, carrier="DL", source_id="dl")
    prefs = RankingPreferences(preferred_carriers=["UA"])
    diff = score_offer(other, prefs).score - score_offer(preferred, prefs).score
    assert diff == pytest.approx(30.0)


def test_avoided_carrier_gets_60_penalty():
    avoided = make_offer(price=600, carrier="F9")
    neutral = make_offer(price=600, carrier="DL", source_id="dl")
    prefs = RankingPreferences(avoid_carriers=["F9"])
    diff = score_offer(avoided, prefs).score - score_offer(neutral, prefs).score
    assert diff == pytest.approx(60.0)


# --- First-takeoff timing ----------------------------------------------------

def test_early_departure_penalized():
    """Default earliest=7. A 5am departure is +$30 vs 11am."""
    redeye = make_offer(price=600, depart_hour=5)
    daytime = make_offer(price=600, depart_hour=11, source_id="day")
    diff = score_offer(redeye, NEUTRAL_PREFS).score - score_offer(daytime, NEUTRAL_PREFS).score
    assert diff == pytest.approx(30.0)


def test_late_night_departure_penalized():
    """Default latest=22. A 23:00 departure is +$30 vs 11am."""
    late = make_offer(price=600, depart_hour=23)
    daytime = make_offer(price=600, depart_hour=11, source_id="day")
    diff = score_offer(late, NEUTRAL_PREFS).score - score_offer(daytime, NEUTRAL_PREFS).score
    assert diff == pytest.approx(30.0)


def test_disabled_depart_threshold_no_penalty():
    """Setting earliest/latest=None disables that threshold."""
    redeye = make_offer(price=600, depart_hour=5)
    daytime = make_offer(price=600, depart_hour=11, source_id="day")
    prefs = RankingPreferences(
        earliest_acceptable_depart_hour=None,
        latest_acceptable_depart_hour=None,
    )
    assert score_offer(redeye, prefs).score == score_offer(daytime, prefs).score


# --- Last-landing timing -----------------------------------------------------

def test_late_arrival_penalized():
    """Default latest_arrive=23. A flight arriving at 23:30 is +$40 vs 14:00."""
    late_arr = make_offer(price=600, depart_hour=10, arrive_hour=23)
    normal_arr = make_offer(price=600, depart_hour=10, arrive_hour=14, source_id="normal")
    diff = score_offer(late_arr, NEUTRAL_PREFS).score - score_offer(normal_arr, NEUTRAL_PREFS).score
    assert diff == pytest.approx(40.0)


def test_early_arrival_penalized():
    """Default earliest_arrive=6. A flight arriving at 4am is +$30 vs 10am."""
    early_arr = make_offer(price=600, depart_hour=20, arrive_hour=4)
    normal_arr = make_offer(price=600, depart_hour=10, arrive_hour=14, source_id="normal")
    diff = score_offer(early_arr, NEUTRAL_PREFS).score - score_offer(normal_arr, NEUTRAL_PREFS).score
    # Note: early_arr departs at 20:00 (within OK range) and arrives at 04:00 next day → only arrival penalty
    assert diff == pytest.approx(30.0)


def test_arrival_uses_last_segment_not_first():
    """Multi-segment offer should consult final-segment arrival, not first."""
    depart = datetime(2026, 6, 15, 10, 0)
    layover_arrive = depart + timedelta(hours=5)  # mid-day landing at hub
    final_depart = layover_arrive + timedelta(hours=1)
    final_arrive = datetime(2026, 6, 16, 23, 30)  # final destination at 23:30 → late penalty
    offer = NormalizedOffer(
        source="amadeus",
        source_id="multi",
        price_usd=Decimal("600"),
        currency="USD",
        total_duration=timedelta(hours=37, minutes=30),
        stops=1,
        segments=[
            Segment(carrier="UA", flight_no="1", origin="SFO", destination="ICN",
                    depart_at=depart, arrive_at=layover_arrive,
                    duration=timedelta(hours=5)),
            Segment(carrier="UA", flight_no="2", origin="ICN", destination="NRT",
                    depart_at=final_depart, arrive_at=final_arrive,
                    duration=timedelta(hours=2)),
        ],
    )
    scored = score_offer(offer, NEUTRAL_PREFS)
    assert scored.breakdown["timing"] == pytest.approx(40.0)  # late-arrival penalty applied


# --- Helper sanity checks ----------------------------------------------------

def test_primary_carrier_extracts_first_segment_carrier():
    offer = make_offer(price=600, carrier="UA")
    assert primary_carrier(offer) == "UA"


def test_relative_price_pct_above_cheapest():
    offer = make_offer(price=900)
    assert relative_price_pct_above_cheapest(offer, Decimal("600")) == pytest.approx(50.0)
    assert relative_price_pct_above_cheapest(offer, None) == 0.0
    assert relative_price_pct_above_cheapest(offer, Decimal("0")) == 0.0


# --- Realistic full-set ranking ----------------------------------------------

def test_ranking_full_set_orders_by_score():
    """Score every offer and assert the ordering reflects the policy.

    Hand-calculated scores (with NEUTRAL_PREFS, all departing 11am, all arriving
    same calendar day at 14:00 — no timing penalties, no carrier prefs):
      a: $950, 11h, 0 stops, UA  → 950 + 55 + 0 - 25 = 980
      b: $620, 18h, 1 stop,  UA  → 620 + 90 + 50 + 0 = 760
      c: $750, 12h, 0 stops, NH  → 750 + 60 + 0 - 25 = 785
      d: $590, 22h, 2 stops, F9  → 590 + 110 + 200 + 0 = 900

    Ranked: b (760) < c (785) < d (900) < a (980).
    The 1-stop bargain wins; the absolute-cheapest 2-stop F9 lands 3rd.
    """
    offers = [
        make_offer(price=950, duration_hours=11, stops=0, carrier="UA", source_id="a"),
        make_offer(price=620, duration_hours=18, stops=1, carrier="UA", source_id="b"),
        make_offer(price=750, duration_hours=12, stops=0, carrier="NH", source_id="c"),
        make_offer(price=590, duration_hours=22, stops=2, carrier="F9", source_id="d"),
    ]
    cheapest = min(o.price_usd for o in offers)
    ranked = sorted(offers, key=lambda o: score_offer(o, NEUTRAL_PREFS, cheapest_price=cheapest).score)
    assert [o.source_id for o in ranked] == ["b", "c", "d", "a"]
