"""🎯 Hook 4: Alert-firing policy for price watches.

Every time the watch checker observes a fresh price for a watched trip, this
module decides whether that observation is worth interrupting the user for,
and if so, what kind of alert it is.

============================================================================
🎯 USER CONTRIBUTION POINT — `evaluate_watch` is yours to write.
============================================================================

Why your judgment matters here:

  • This is the alert-fatigue vs. missed-deal trade-off, and it defines the
    product. Fire on every dip and the user mutes the tool; fire only on
    target-hit and a watch with no target set NEVER alerts, even when the
    fare crashes 40% overnight.

  • The rolling state in `WatchSnapshot` is everything the checker has
    remembered for you: last observed price, lowest ever seen, what you last
    alerted at and when. The policy question is which *changes* in that
    state constitute news.

Trade-offs to consider:
  • Absolute target ("alert under $800") is precise but requires the user to
    know what a good price is. Relative drops ("fell 15% since last check")
    work with zero configuration but can fire on noise — fare APIs jitter a
    few percent between sources.
  • Debouncing: once you've alerted at $750, a re-observation of $748 six
    hours later is not news. A further drop to $650 is. Percentage-based
    re-alert thresholds (e.g. must be 5% below last alert) age well.
  • NEW_LOW is a great zero-config signal ("cheapest we've ever seen for
    this trip") — but only once history exists; the second-ever observation
    shouldn't fire just because it's $1 under the first.
  • Departure proximity changes urgency: a modest drop 10 days out may be
    the last good exit; the same drop 200 days out is routine.

The default implementation below only fires TARGET_HIT, with a simple
"must beat the last alerted price" debounce. Extend it with your policy —
the xfail tests in tests/test_alert_rules.py encode suggested behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class AlertKind(str, Enum):
    TARGET_HIT = "target_hit"      # Price at or below the user's target.
    PRICE_DROP = "price_drop"      # Significant relative drop since last check.
    NEW_LOW = "new_low"            # Cheapest price ever observed for this watch.
    PRICE_SPIKE = "price_spike"    # Price rising fast — "book before it climbs".


@dataclass
class PriceObservation:
    """A fresh price the checker just observed. Input to the hook."""

    price_usd: Decimal
    source: str                      # which provider returned the cheapest offer
    observed_at: datetime


@dataclass
class WatchSnapshot:
    """Rolling state for the watch at the moment of observation."""

    target_price_usd: Decimal | None      # user's target, if they set one
    last_price_usd: Decimal | None        # previous observation (None on first check)
    lowest_seen_usd: Decimal | None       # lowest ever observed (None on first check)
    last_alerted_price_usd: Decimal | None
    last_alerted_at: datetime | None
    days_until_departure: int


@dataclass
class AlertDecision:
    fire: bool
    kind: AlertKind | None = None
    message: str = ""


def no_alert() -> AlertDecision:
    return AlertDecision(fire=False)


# =============================================================================
# 🎯 HOOK 4 — IMPLEMENT THIS
# =============================================================================

def evaluate_watch(observation: PriceObservation, snapshot: WatchSnapshot) -> AlertDecision:
    """Decide whether this observation should fire an alert, and which kind.

    The default implementation fires TARGET_HIT when the price is at/below
    the user's target and beats any previously-alerted price. Watches with
    no target never alert. Replace with your own policy.
    """
    # =========================================================================
    # ✏️ YOUR LOGIC HERE — behaviors the xfail tests suggest:
    #
    # 1. PRICE_DROP without a target:
    #    if snapshot.last_price_usd and drop_pct >= 0.15: fire PRICE_DROP
    #    (pick your threshold — 15%? 10%? scale by days_until_departure?)
    #
    # 2. NEW_LOW once real history exists:
    #    if snapshot.lowest_seen_usd and price < lowest_seen: fire NEW_LOW
    #    (maybe require it to be meaningfully lower, not $1)
    #
    # 3. Re-alert debounce by percentage, not just "any lower":
    #    already alerted at $750 → $748 is noise, $700 (-6.7%) is news.
    #
    # 4. PRICE_SPIKE near departure:
    #    rising ≥20% inside 21 days of departure → "book now before it climbs"?
    # =========================================================================

    price = observation.price_usd
    target = snapshot.target_price_usd

    if target is None or price > target:
        return no_alert()

    # Debounce: don't re-fire unless this beats the price we last alerted at.
    if snapshot.last_alerted_price_usd is not None and price >= snapshot.last_alerted_price_usd:
        return no_alert()

    return AlertDecision(
        fire=True,
        kind=AlertKind.TARGET_HIT,
        message=(
            f"Price ${price:,.0f} is at or below your target ${target:,.0f} "
            f"({snapshot.days_until_departure} days until departure)."
        ),
    )
