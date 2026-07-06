"""🎯 Hook 3: Hidden-fare risk scoring. (IMPLEMENTED)

When the discovery service finds a non-standard fare strategy (skiplagging,
split-ticket, etc.), this module decides:
  • How risky is it on a LOW / MEDIUM / HIGH / EXTREME scale.
  • What concrete risks apply (bag check, return cancellation, loyalty closure,
    missed-connection liability, etc.).
  • Whether the strategy is even *appropriate* given the request shape —
    DISQUALIFIED candidates are dropped by the discovery service entirely.

Calibration rationale:
  • Hidden-city + round-trip is DISQUALIFIED, not merely EXTREME: skipping a
    leg cancels every later leg in the PNR, so the return is structurally
    gone. There is no "careful" way to do it — don't even show it.
  • Hidden-city + checked bag is EXTREME: bags are tagged to the booked
    final destination. That's a certain loss, unlike the probabilistic risks.
  • Hidden-city carry-on one-way is HIGH, never lower: loyalty retaliation
    and involuntary rerouting (around your real destination, with no
    recourse) apply even to tame domestic skips.
  • Split-ticket severity hinges on carrier continuity: same-carrier is LOW
    (administrative hassle only); cross-carrier is HIGH because there is no
    interline protection when the first ticket melts down.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from app.integrations.types import Segment


class FareStrategy(str, Enum):
    HIDDEN_CITY = "hidden_city"
    SPLIT_TICKET = "split_ticket"
    MULTI_CITY = "multi_city"


class RiskLevel(str, Enum):
    LOW = "LOW"                     # Minimal practical risk; mostly disclosure.
    MEDIUM = "MEDIUM"                # Real but manageable with care.
    HIGH = "HIGH"                    # Serious downsides; user should know.
    EXTREME = "EXTREME"              # Loyalty closure / lawsuit / no recovery.
    DISQUALIFIED = "DISQUALIFIED"    # Don't even surface this candidate.


@dataclass
class HiddenFareCandidate:
    """A candidate fare strategy under consideration. Inputs to the hook."""

    strategy: FareStrategy
    price_usd: Decimal
    real_destination: str               # Where the user actually wants to land
    final_destination: str               # Where the booked itinerary actually ends
    useful_segments: list[Segment]       # Legs the user will fly
    full_segments: list[Segment]         # All legs on the booked itinerary
    has_return: bool = False             # Did the user request a round-trip?
    has_checked_bag: bool = False        # User intends to check a bag
    cross_carrier: bool = False          # Multiple operating carriers
    booking_url: str | None = None
    raw: dict | None = None


@dataclass
class RiskFlag:
    """A single named risk with severity + advice."""

    code: str                       # short stable identifier ('bag_loss', 'pnr_cancel', etc.)
    severity: RiskLevel             # LOW / MEDIUM / HIGH / EXTREME
    description: str                # human-readable, displayed verbatim


@dataclass
class RiskAssessment:
    overall_level: RiskLevel
    reasoning: str
    flags: list[RiskFlag] = field(default_factory=list)


# =============================================================================
# 🎯 HOOK 3 — Implemented classification
# =============================================================================

def _score_hidden_city(candidate: HiddenFareCandidate) -> RiskAssessment:
    # Structurally broken: skipping the outbound's last leg auto-cancels every
    # remaining leg in the PNR — including the entire return. Never surface it.
    if candidate.has_return:
        return RiskAssessment(
            overall_level=RiskLevel.DISQUALIFIED,
            reasoning=(
                "Hidden-city on a round-trip never works: skipping a leg "
                "cancels all later legs in the PNR, so the return would vanish."
            ),
            flags=[FLAG_PNR_CANCEL],
        )

    flags = [FLAG_PNR_CANCEL, FLAG_LOYALTY_CLOSURE, FLAG_AIRLINE_LITIGATION]

    # Checked bags route to the BOOKED final destination, not where you get
    # off. That's a guaranteed loss, not a maybe — top of the scale.
    if candidate.has_checked_bag:
        return RiskAssessment(
            overall_level=RiskLevel.EXTREME,
            reasoning=(
                "You intend to check a bag on a hidden-city itinerary — it "
                f"would be tagged through to {candidate.final_destination}, "
                f"not {candidate.real_destination}. Carry-on only, or skip "
                "this strategy."
            ),
            flags=[FLAG_BAG_LOSS, *flags],
        )

    # Carry-on one-way: the workable case, but skiplagging is never LOW.
    # Loyalty retaliation and involuntary-reroute exposure (the airline can
    # reroute you AROUND your real destination) keep it HIGH.
    return RiskAssessment(
        overall_level=RiskLevel.HIGH,
        reasoning=(
            f"Carry-on one-way hidden-city: get off at {candidate.real_destination} "
            f"and abandon the leg(s) to {candidate.final_destination}. Workable, "
            "but if the airline reroutes you around your real destination there "
            "is no recourse, and repeat use risks loyalty-account action."
        ),
        flags=[FLAG_BAG_LOSS, *flags],
    )


def _score_split_ticket(candidate: HiddenFareCandidate) -> RiskAssessment:
    if candidate.cross_carrier:
        # Two unrelated contracts on different carriers: if ticket 1 melts
        # down, carrier 2 owes nothing and rebooking is at walk-up prices.
        return RiskAssessment(
            overall_level=RiskLevel.HIGH,
            reasoning=(
                "Split tickets on different carriers: no interline protection. "
                "If the first ticket cancels or delays, the second carrier has "
                "no obligation to you — build in a large buffer or buy "
                "protection (e.g. book via an OTA with a connection guarantee)."
            ),
            flags=[FLAG_NO_INTERLINE_PROTECTION, FLAG_CROSS_CARRIER_BUFFER],
        )

    # Same carrier / same alliance: barely riskier than a normal round-trip.
    # The residual gotchas are administrative (two PNRs to change separately).
    return RiskAssessment(
        overall_level=RiskLevel.LOW,
        reasoning=(
            "Two one-ways on the same carrier — practically the same risk as "
            "a round-trip. Changes/cancellations must be handled per ticket."
        ),
        flags=[
            RiskFlag(
                code="separate_pnrs",
                severity=RiskLevel.LOW,
                description=(
                    "Two separate bookings: schedule changes and refunds are "
                    "handled independently for each ticket."
                ),
            )
        ],
    )


def score_hidden_fare_risk(candidate: HiddenFareCandidate) -> RiskAssessment:
    """Classify the candidate's overall risk and surface specific flags.

    HIDDEN_CITY: DISQUALIFIED with a return; EXTREME with a checked bag;
    otherwise HIGH (skiplagging is never LOW). SPLIT_TICKET: HIGH across
    carriers (no interline protection), LOW on one carrier. MULTI_CITY:
    MEDIUM pending real open-jaw analysis.
    """
    if candidate.strategy == FareStrategy.HIDDEN_CITY:
        return _score_hidden_city(candidate)
    if candidate.strategy == FareStrategy.SPLIT_TICKET:
        return _score_split_ticket(candidate)

    return RiskAssessment(
        overall_level=RiskLevel.MEDIUM,
        reasoning=(
            "Multi-city/open-jaw itineraries are usually fine but can involve "
            "positioning flights and separate tickets — review the details."
        ),
        flags=[
            RiskFlag(
                code="review_itinerary",
                severity=RiskLevel.MEDIUM,
                description=(
                    "Unconventional routing — confirm each ticket's change "
                    "rules and any self-transfer segments before booking."
                ),
            )
        ],
    )


# =============================================================================
# Reusable risk-flag constants — feel free to use, modify, or define your own.
# =============================================================================


FLAG_BAG_LOSS = RiskFlag(
    code="bag_loss",
    severity=RiskLevel.HIGH,
    description="Cannot check bags — they'd be sent to the final destination, not where you're getting off.",
)

FLAG_PNR_CANCEL = RiskFlag(
    code="pnr_cancel",
    severity=RiskLevel.EXTREME,
    description="If you skip a leg, the airline auto-cancels all subsequent legs in the same PNR. NEVER use this on a round-trip — your return will vanish.",
)

FLAG_LOYALTY_CLOSURE = RiskFlag(
    code="loyalty_closure",
    severity=RiskLevel.HIGH,
    description="Airlines have closed accounts and confiscated miles for repeat skiplaggers. Don't include this booking in your loyalty number.",
)

FLAG_AIRLINE_LITIGATION = RiskFlag(
    code="airline_litigation",
    severity=RiskLevel.MEDIUM,
    description="Lufthansa and others have pursued collection actions against frequent skiplaggers. Rare but possible.",
)

FLAG_NO_INTERLINE_PROTECTION = RiskFlag(
    code="no_interline",
    severity=RiskLevel.HIGH,
    description="Different carriers — if your first ticket is delayed/cancelled, the second carrier owes you nothing.",
)

FLAG_CROSS_CARRIER_BUFFER = RiskFlag(
    code="cross_carrier_buffer",
    severity=RiskLevel.MEDIUM,
    description="Cross-carrier transfer — allow at least 3 hours buffer in case of misconnection.",
)
