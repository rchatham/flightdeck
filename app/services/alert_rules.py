"""🎯 Hook 4: Alert-firing policy for price watches. (IMPLEMENTED)

Every time the watch checker observes a fresh price for a watched trip, this
module decides whether that observation is worth interrupting the user for,
and if so, what kind of alert it is.

This is the alert-fatigue vs. missed-deal trade-off, and it defines the
product: fire on every dip and the user mutes the tool; fire only on
target-hit and a watch with no target set never alerts, even when the fare
crashes 40% overnight.

Implemented policy (thresholds are module constants — tune freely):
  • TARGET_HIT   — price at/below the user's target.
  • PRICE_DROP   — ≥10% below the previous check; works with no target set.
  • NEW_LOW      — ≥3% below the cheapest price ever seen for this trip.
  • PRICE_SPIKE  — ≥20% above the previous check within 21 days of
    departure: "if you're going, book now before it climbs further."

Downward alerts share a percentage debounce: after alerting at $750, a
re-observation must be ≥2% cheaper (below jitter) to fire again. Spikes are
time-debounced (24h) instead, since they move away from any prior alert.
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
# 🎯 HOOK 4 — Implemented policy
# =============================================================================
#
# Tunable thresholds. The calibration story:
#   • REALERT_IMPROVEMENT (2%): once we've alerted, a re-observation must be
#     ≥2% cheaper than the alerted price to fire again. Fare APIs jitter 1-2%
#     between sources; below that is noise, not news.
#   • DROP_PCT (10%): zero-config signal. 10% clears inter-source jitter and
#     ordinary daily wobble while catching genuine fare drops. Scaling this by
#     days_until_departure was considered and rejected: a big drop far out is
#     still actionable (book early), so one threshold keeps behavior legible.
#   • NEW_LOW_PCT (3%): "cheapest ever seen" needs real improvement, not a $1
#     undercut of yesterday. Softer than DROP_PCT because beating the all-time
#     low is itself informative even when the step from last check is small.
#   • SPIKE_PCT (20%) inside SPIKE_WINDOW_DAYS (21): close to departure a
#     sharp rise means the fare bucket is emptying — the useful alert is
#     "book NOW before it climbs further". Debounced to one per 24h since a
#     spike alert can't beat-the-last-price like downward alerts do.

REALERT_IMPROVEMENT = Decimal("0.02")   # re-alert only if ≥2% below last alert
DROP_PCT = Decimal("0.10")              # PRICE_DROP: ≥10% below last check
NEW_LOW_PCT = Decimal("0.03")           # NEW_LOW: ≥3% below all-time low
SPIKE_PCT = Decimal("0.20")             # PRICE_SPIKE: ≥20% above last check…
SPIKE_WINDOW_DAYS = 21                  # …within 3 weeks of departure
SPIKE_COOLDOWN_HOURS = 24


def _debounced(price: Decimal, snapshot: WatchSnapshot) -> bool:
    """True if a downward alert should stay quiet given what we last alerted."""
    last = snapshot.last_alerted_price_usd
    return last is not None and price >= last * (1 - REALERT_IMPROVEMENT)


def evaluate_watch(observation: PriceObservation, snapshot: WatchSnapshot) -> AlertDecision:
    """Decide whether this observation should fire an alert, and which kind.

    Precedence: TARGET_HIT > PRICE_DROP > NEW_LOW > PRICE_SPIKE. The first
    three are downward signals sharing the percentage debounce; the spike
    path is upward and time-debounced instead.
    """
    price = observation.price_usd
    target = snapshot.target_price_usd
    last = snapshot.last_price_usd
    lowest = snapshot.lowest_seen_usd
    days_out = snapshot.days_until_departure

    # --- TARGET_HIT: the user told us exactly what a good price is. ----------
    if target is not None and price <= target and not _debounced(price, snapshot):
        return AlertDecision(
            fire=True,
            kind=AlertKind.TARGET_HIT,
            message=(
                f"Price ${price:,.0f} is at or below your target ${target:,.0f} "
                f"({days_out} days until departure)."
            ),
        )

    # --- PRICE_DROP: big move since last check, no target needed. ------------
    if last is not None and last > 0:
        drop = (last - price) / last
        if drop >= DROP_PCT and not _debounced(price, snapshot):
            return AlertDecision(
                fire=True,
                kind=AlertKind.PRICE_DROP,
                message=(
                    f"Price fell {float(drop) * 100:.0f}% since the last check: "
                    f"${last:,.0f} → ${price:,.0f} ({days_out} days until departure)."
                ),
            )

    # --- NEW_LOW: meaningfully cheaper than anything we've ever seen. --------
    if lowest is not None and lowest > 0:
        if price <= lowest * (1 - NEW_LOW_PCT) and not _debounced(price, snapshot):
            return AlertDecision(
                fire=True,
                kind=AlertKind.NEW_LOW,
                message=(
                    f"New all-time low for this trip: ${price:,.0f} "
                    f"(previous low ${lowest:,.0f}, {days_out} days until departure)."
                ),
            )

    # --- PRICE_SPIKE: fare climbing fast close to departure. -----------------
    if (
        last is not None
        and last > 0
        and days_out <= SPIKE_WINDOW_DAYS
        and price >= last * (1 + SPIKE_PCT)
    ):
        recently_alerted = (
            snapshot.last_alerted_at is not None
            and (observation.observed_at - snapshot.last_alerted_at).total_seconds()
            < SPIKE_COOLDOWN_HOURS * 3600
        )
        if not recently_alerted:
            rise = (price - last) / last
            return AlertDecision(
                fire=True,
                kind=AlertKind.PRICE_SPIKE,
                message=(
                    f"Price jumped {float(rise) * 100:.0f}% "
                    f"(${last:,.0f} → ${price:,.0f}) with only {days_out} days "
                    f"until departure — if you're going, book now."
                ),
            )

    return no_alert()
