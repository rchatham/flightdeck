"""🎯 Hook 1: Flight offer ranking.

This module is the SCORING heart of the route optimizer. After offers are
fetched from all sources and deduplicated, every remaining offer is scored
by `score_offer()`. Lower scores rank better.

============================================================================
🎯 USER CONTRIBUTION POINT — `score_offer` is yours to write.
============================================================================

You decide what "best flight" means for FlightDeck. The scaffolding around
this function (fetching, dedup, persistence, CLI rendering) is done — your
5–10 lines of logic shape what the user actually sees at the top of every
search.

Trade-offs to consider:
  • Price weight: linear in dollars? Or percent above the cheapest in the
    set? Linear treats $50 the same on a $200 ticket as on a $2000 ticket;
    relative weighting penalizes bad-value outliers regardless of trip cost.
  • Duration weight: every extra hour matters more for a 4-hour flight than
    a 14-hour flight (fatigue is sub-linear). Or you might say "any time
    spent over 12 hours is hell, weight steeply above that threshold."
  • Stops: a 1-stop is often acceptable; a 2-stop is almost never. A simple
    linear penalty understates this. Consider an exponential penalty.
  • Departure time of day: red-eye departures (00:00–05:00) and very early
    morning (05:00–07:00) often warrant a small score penalty. Sunday-evening
    departures are a known awful slot. Most users want this; some don't.
  • Carrier preference: `prefs.preferred_carriers` lets the user thumb the
    scale. How heavily? Worth a 5% discount? 15%?

You can ignore any field if you don't think it matters. Scoring is opinion;
make it yours.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.integrations.types import NormalizedOffer


@dataclass
class RankingPreferences:
    """User-tunable inputs to `score_offer`. All optional with sensible defaults."""

    # Carrier favorites. Score discount applied when offer's primary carrier
    # is in this list. Empty = no preference.
    preferred_carriers: list[str] = field(default_factory=list)

    # Avoid these carriers (e.g., bad past experience). Score penalty applied.
    avoid_carriers: list[str] = field(default_factory=list)

    # First-segment departure-time thresholds. Penalty applied when departure
    # hour falls outside [earliest, latest). None on either side disables that
    # check. Defaults reflect the user's preference: avoid takeoffs before 7am
    # or at/after 10pm.
    earliest_acceptable_depart_hour: int | None = 7
    latest_acceptable_depart_hour: int | None = 22

    # Last-segment arrival-time thresholds (i.e., the actual destination
    # touchdown, not a layover). Defaults: avoid arrivals before 6am or at/after
    # 11pm — late arrivals are worse than early departures since you land tired.
    earliest_acceptable_arrive_hour: int | None = 6
    latest_acceptable_arrive_hour: int | None = 23

    # Stacks an additional bonus on nonstop flights, on top of the stops penalty.
    prefer_nonstop: bool = True


@dataclass
class ScoredOffer:
    """An offer paired with its computed score. Lower = better."""

    offer: NormalizedOffer
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)


# =============================================================================
# 🎯 HOOK 1 — IMPLEMENT THIS
# =============================================================================

def score_offer(
    offer: NormalizedOffer,
    prefs: RankingPreferences,
    *,
    cheapest_price: Decimal | None = None,
) -> ScoredOffer:
    """Compute a comparison score for `offer`. Lower scores rank better.

    Scoring philosophy (per FlightDeck owner):
      • Linear USD price baseline — cheapest naturally wins by big gaps,
        other factors only break near-ties.
      • +$5 per hour of total trip duration.
      • Stops penalty: 50 × stops² (1-stop +$50, 2-stop +$200, 3-stop +$450).
      • Nonstop bonus: −$25 on top of the (zero) stops penalty.
      • First-flight-takeoff penalties: +$30 if before earliest_acceptable_depart_hour
        OR at/after latest_acceptable_depart_hour.
      • Last-flight-landing penalties (the actual destination touchdown, not a
        layover): +$40 if at/after latest_acceptable_arrive_hour, +$30 if before
        earliest_acceptable_arrive_hour.
      • Carrier favorite: −$30. Avoid carrier: +$60.
    """
    price_score = float(offer.price_usd)
    duration_hours = offer.total_duration.total_seconds() / 3600
    duration_penalty = duration_hours * 5.0
    stops_penalty = 50.0 * (offer.stops ** 2)
    nonstop_bonus = -25.0 if (prefs.prefer_nonstop and offer.stops == 0) else 0.0

    timing_penalty = 0.0
    carrier_adjust = 0.0

    if offer.segments:
        first_dep_hour = offer.segments[0].depart_at.hour
        last_arr_hour = offer.segments[-1].arrive_at.hour

        if (prefs.earliest_acceptable_depart_hour is not None
                and first_dep_hour < prefs.earliest_acceptable_depart_hour):
            timing_penalty += 30.0
        if (prefs.latest_acceptable_depart_hour is not None
                and first_dep_hour >= prefs.latest_acceptable_depart_hour):
            timing_penalty += 30.0
        if (prefs.latest_acceptable_arrive_hour is not None
                and last_arr_hour >= prefs.latest_acceptable_arrive_hour):
            timing_penalty += 40.0
        if (prefs.earliest_acceptable_arrive_hour is not None
                and last_arr_hour < prefs.earliest_acceptable_arrive_hour):
            timing_penalty += 30.0

        primary = offer.segments[0].carrier
        if primary in prefs.preferred_carriers:
            carrier_adjust -= 30.0
        if primary in prefs.avoid_carriers:
            carrier_adjust += 60.0

    score = (
        price_score
        + duration_penalty
        + stops_penalty
        + nonstop_bonus
        + timing_penalty
        + carrier_adjust
    )
    return ScoredOffer(
        offer=offer,
        score=score,
        breakdown={
            "price": price_score,
            "duration": duration_penalty,
            "stops": stops_penalty,
            "nonstop_bonus": nonstop_bonus,
            "timing": timing_penalty,
            "carrier": carrier_adjust,
        },
    )


# =============================================================================
# Helpers — feel free to use these in your implementation, or write your own.
# =============================================================================


def first_departure(offer: NormalizedOffer) -> datetime | None:
    """The first segment's departure time, or None if no segments."""
    return offer.segments[0].depart_at if offer.segments else None


def primary_carrier(offer: NormalizedOffer) -> str | None:
    """The carrier of the first segment (usually the marketing carrier)."""
    return offer.segments[0].carrier if offer.segments else None


def relative_price_pct_above_cheapest(
    offer: NormalizedOffer, cheapest_price: Decimal | None
) -> float:
    """Return percentage above cheapest price in the set, or 0 if cheapest_price is None."""
    if cheapest_price is None or cheapest_price <= 0:
        return 0.0
    return float((offer.price_usd - cheapest_price) / cheapest_price) * 100.0
