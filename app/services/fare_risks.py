"""🎯 Hook 3: Hidden-fare risk scoring.

When the discovery service finds a non-standard fare strategy (skiplagging,
split-ticket, etc.), this module decides:
  • How risky is it on a LOW / MEDIUM / HIGH / EXTREME scale.
  • What concrete risks apply (bag check, return cancellation, loyalty closure,
    missed-connection liability, etc.).
  • Whether the strategy is even *appropriate* given the request shape.

============================================================================
🎯 USER CONTRIBUTION POINT — `score_hidden_fare_risk` is yours to write.
============================================================================

Why your judgment matters here:

  • Skiplagging carries different consequences than split-ticketing. The CLI
    will display whatever risks you classify as applicable. If you mark a risk
    as "always applies to hidden_city" but it actually depends on whether the
    user is checking bags, your warnings will be wrong.

  • The risk *level* shapes the visual treatment in the CLI (LOW = green,
    EXTREME = red). Calibration matters: classify all hidden-city as EXTREME
    and the CLI screams "danger" for tame intra-EU domestic skips. Classify
    nothing as EXTREME and a user could end up with their loyalty account
    torched without warning.

  • You can disqualify candidates entirely — return RiskLevel.DISQUALIFIED
    with a reason. The discovery service will skip them.

Trade-offs to consider:
  • Skiplagging is ALWAYS at least HIGH on a multi-segment international
    itinerary — bag risk + loyalty risk + airline retaliation are real.
  • Skiplagging is more like MEDIUM on a domestic one-way with carry-on only.
  • Split-ticket on the same alliance/carrier: low-risk; on different
    carriers with tight connection: high-risk. Cross-carrier without
    intentional buffer is the dangerous pattern.
  • Frequent skiplagging on the same carrier — the next-tier risk you can't
    detect from one search but can warn about generally.
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
# 🎯 HOOK 3 — IMPLEMENT THIS
# =============================================================================

def score_hidden_fare_risk(candidate: HiddenFareCandidate) -> RiskAssessment:
    """Classify the candidate's overall risk and surface specific flags.

    The default implementation classifies everything as MEDIUM with a generic
    warning. Replace with your own per-strategy / per-context logic.
    """
    # =========================================================================
    # ✏️ YOUR LOGIC HERE — branches you might want:
    #
    # if candidate.strategy == FareStrategy.HIDDEN_CITY:
    #     flags = [_FLAG_BAG_LOSS, _FLAG_PNR_CANCEL]
    #     if candidate.has_return:
    #         return RiskAssessment(DISQUALIFIED, "Hidden-city + round-trip never works", ...)
    #     if candidate.has_checked_bag:
    #         flags.append(_FLAG_BAG_LOSS_HARD)
    #     # International multi-segment vs domestic carry-on differs in severity
    #     return RiskAssessment(HIGH if international else MEDIUM, ..., flags)
    #
    # if candidate.strategy == FareStrategy.SPLIT_TICKET:
    #     if candidate.cross_carrier:
    #         return RiskAssessment(HIGH, "Cross-carrier split — no protection if leg 1 cancels")
    #     return RiskAssessment(LOW, "Same-carrier split — low risk")
    # =========================================================================

    return RiskAssessment(
        overall_level=RiskLevel.MEDIUM,
        reasoning="Default stub — implement score_hidden_fare_risk for real classification.",
        flags=[
            RiskFlag(
                code="default_warning",
                severity=RiskLevel.MEDIUM,
                description="This is an unconventional fare strategy with real downsides; review carefully before booking.",
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
