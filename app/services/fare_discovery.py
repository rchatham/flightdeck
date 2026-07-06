"""Fare discovery service.

Finds savings opportunities outside vanilla one-search-one-itinerary booking:
  • Hidden-city ("skiplagging") via Kiwi's `virtually_interlined=True` results
    where the candidate's final destination is past your real destination.
  • Split-ticket: combine independent outbound + return one-ways.
  • Multi-city / open-jaw: fly into one city, out of another nearby.

Each opportunity is run through the `score_hidden_fare_risk` hook so the CLI
can surface the strategy with clear warnings.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.api.schemas.search import SearchRequest
from app.integrations.kiwi import KiwiClient, KiwiError
from app.services.fare_risks import (
    FareStrategy,
    HiddenFareCandidate,
    RiskAssessment,
    RiskLevel,
    score_hidden_fare_risk,
)
from app.services.route_optimizer import _fan_out_sources

logger = logging.getLogger(__name__)


@dataclass
class FareOpportunity:
    """A potential savings strategy with its risk assessment."""

    candidate: HiddenFareCandidate
    risk: RiskAssessment
    direct_price_usd: Decimal      # cheapest direct/regular fare for the same trip
    savings_usd: Decimal
    savings_pct: float
    booking_steps: list[str] = field(default_factory=list)


# --- Strategy: Hidden-city (skiplagging) -------------------------------------


async def _find_hidden_city_candidates(req: SearchRequest) -> list[HiddenFareCandidate]:
    """Search Kiwi with virtually_interlined=True; filter to candidates whose
    final destination is past the user's real destination (i.e., the user's
    real destination appears as a layover/intermediate stop)."""
    candidates: list[HiddenFareCandidate] = []
    async with KiwiClient() as client:
        try:
            offers = await client.search_flight_offers(
                origin=req.origin,
                destination="anywhere",  # placeholder — real call uses actual dest
                departure_date=req.departure_date,
                return_date=None,  # one-way only for hidden-city
                adults=req.passengers,
                cabin_class=req.cabin_class,
                non_stop=False,
                virtually_interlined=True,
            )
        except KiwiError as e:
            logger.warning("Kiwi hidden-city search failed: %s", e)
            return []
        except Exception as e:  # noqa: BLE001
            logger.exception("Kiwi hidden-city search crashed: %s", e)
            return []

    for offer in offers:
        if not offer.segments:
            continue
        # Find candidates whose route passes through req.destination but ends
        # somewhere else. The user "gets off" at the layover.
        intermediate_stops = [s.destination for s in offer.segments[:-1]]
        if req.destination.upper() in intermediate_stops:
            real_arrival_idx = intermediate_stops.index(req.destination.upper())
            useful_segments = offer.segments[: real_arrival_idx + 1]
            candidates.append(
                HiddenFareCandidate(
                    strategy=FareStrategy.HIDDEN_CITY,
                    price_usd=offer.price_usd,
                    real_destination=req.destination.upper(),
                    final_destination=offer.segments[-1].destination,
                    useful_segments=useful_segments,
                    full_segments=offer.segments,
                    has_return=False,
                    has_checked_bag=False,
                    booking_url=offer.deep_link or offer.booking_url,
                    raw=offer.raw,
                )
            )
    return candidates


# --- Strategy: Split-ticket --------------------------------------------------


async def _find_split_ticket_candidates(req: SearchRequest) -> list[HiddenFareCandidate]:
    """Independently search outbound + return as one-ways; combine cheapest pair."""
    if not req.return_date:
        return []  # split-ticket only applies to round-trips

    outbound_req = SearchRequest(
        origin=req.origin, destination=req.destination,
        departure_date=req.departure_date, return_date=None,
        passengers=req.passengers, cabin_class=req.cabin_class,
        include_nearby=req.include_nearby,
    )
    inbound_req = SearchRequest(
        origin=req.destination, destination=req.origin,
        departure_date=req.return_date, return_date=None,
        passengers=req.passengers, cabin_class=req.cabin_class,
        include_nearby=req.include_nearby,
    )

    outbound, inbound = await _fan_out_sources(outbound_req), await _fan_out_sources(inbound_req)
    if not outbound or not inbound:
        return []

    cheapest_out = min(outbound, key=lambda o: o.price_usd)
    cheapest_in = min(inbound, key=lambda o: o.price_usd)
    combined_price = cheapest_out.price_usd + cheapest_in.price_usd

    # Cross-carrier flag: split is more interesting (and slightly riskier) when
    # the two legs are on different airlines.
    out_carrier = cheapest_out.segments[0].carrier if cheapest_out.segments else ""
    in_carrier = cheapest_in.segments[0].carrier if cheapest_in.segments else ""
    cross_carrier = out_carrier != in_carrier

    return [
        HiddenFareCandidate(
            strategy=FareStrategy.SPLIT_TICKET,
            price_usd=combined_price,
            real_destination=req.destination.upper(),
            final_destination=req.destination.upper(),
            useful_segments=cheapest_out.segments + cheapest_in.segments,
            full_segments=cheapest_out.segments + cheapest_in.segments,
            has_return=True,
            has_checked_bag=True,
            cross_carrier=cross_carrier,
            booking_url=None,
            raw={"outbound": cheapest_out.raw, "inbound": cheapest_in.raw},
        )
    ]


# --- Public entrypoint -------------------------------------------------------


async def discover_opportunities(
    req: SearchRequest,
    strategies: Sequence[FareStrategy],
) -> list[FareOpportunity]:
    """Find every requested-strategy opportunity, score risk, return sorted by savings."""
    # Direct-fare baseline for savings calculations
    direct_offers = await _fan_out_sources(req)
    direct_price = min((o.price_usd for o in direct_offers), default=None)

    candidates: list[HiddenFareCandidate] = []
    if FareStrategy.HIDDEN_CITY in strategies:
        candidates.extend(await _find_hidden_city_candidates(req))
    if FareStrategy.SPLIT_TICKET in strategies:
        candidates.extend(await _find_split_ticket_candidates(req))
    # Multi-city / open-jaw deferred — same machinery once user pairs cities.

    opportunities: list[FareOpportunity] = []
    for c in candidates:
        risk = score_hidden_fare_risk(c)
        # Hook 3 contract: DISQUALIFIED candidates are never surfaced.
        if risk.overall_level == RiskLevel.DISQUALIFIED:
            logger.info("dropping disqualified %s candidate: %s",
                        c.strategy.value, risk.reasoning)
            continue
        if direct_price is None or direct_price <= 0:
            savings_usd = Decimal("0")
            savings_pct = 0.0
        else:
            savings_usd = direct_price - c.price_usd
            savings_pct = float(savings_usd / direct_price) * 100.0
        # Skip "opportunities" that aren't actually cheaper
        if direct_price is not None and savings_usd <= 0:
            continue
        opportunities.append(
            FareOpportunity(
                candidate=c,
                risk=risk,
                direct_price_usd=direct_price or Decimal("0"),
                savings_usd=savings_usd,
                savings_pct=savings_pct,
                booking_steps=_booking_steps_for(c),
            )
        )
    opportunities.sort(key=lambda o: -o.savings_usd)  # biggest savings first
    return opportunities


def _booking_steps_for(c: HiddenFareCandidate) -> list[str]:
    """Generate human-readable booking instructions for the strategy."""
    if c.strategy == FareStrategy.HIDDEN_CITY:
        path = " → ".join([c.useful_segments[0].origin] +
                          [s.destination for s in c.full_segments])
        return [
            f"Book this itinerary: {path}",
            f"Your real destination is {c.real_destination} — get off there.",
            "DO NOT check bags (they'd go to the final destination).",
            "DO NOT include this in your loyalty account if you do this often.",
            "If round-trip, ALL subsequent legs may auto-cancel — book one-way.",
        ]
    if c.strategy == FareStrategy.SPLIT_TICKET:
        steps = [
            "Book outbound separately as a one-way.",
            "Book return separately as a one-way.",
        ]
        if c.cross_carrier:
            steps.append(
                "Different carriers — no protection between tickets if first leg cancels."
            )
        steps.append("Allow extra buffer time at the connection city if applicable.")
        return steps
    return []
