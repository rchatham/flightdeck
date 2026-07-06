"""🎯 Hook 2: Booking-window recommendation.

Given a route's price history and how many days until departure, decide
whether the user should book now, wait, or it's too close to call.

============================================================================
🎯 USER CONTRIBUTION POINT — `recommend_booking_window` is yours to write.
============================================================================

The scaffolding around this function fetches `price_history` rows, computes
median/min/max/current-percent-above-median, and hands you a tidy struct.
Your 5–10 lines decide what to *do* with those numbers.

Trade-offs to consider:
  • The widely-cited "book 6–8 weeks before international" heuristic is
    wrong as often as it's right. With your own price-history data you can
    do better — but only if you have *enough* data. With <20 samples you
    probably shouldn't make confident recommendations.
  • "Below average" is not the same as "buy now." Prices that just dropped
    might keep dropping. A rising trend in the last 7 days is a stronger
    "buy" signal than a single low data point.
  • Days-until-departure matters non-linearly: at 60+ days out, "wait and
    see" is reasonable. At 14 days out, prices typically only go up — even
    a slightly-above-median price may be worth grabbing.
  • Confidence calibration: if you don't have much data or the price is
    near-median, say "neutral" and explain why. False confidence is worse
    than no recommendation.

Outputs the hook should aim for:
  • A clear `verdict` (BUY_NOW / WAIT / NEUTRAL / TOO_CLOSE_TO_CALL).
  • A `confidence` 0.0–1.0.
  • A `reasoning` string the CLI surfaces verbatim — write it for human eyes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Verdict(str, Enum):
    BUY_NOW = "BUY_NOW"            # Price is good; lock it in.
    WAIT = "WAIT"                   # Prices likely to drop further.
    NEUTRAL = "NEUTRAL"             # No strong signal either way.
    TOO_CLOSE_TO_CALL = "TOO_CLOSE_TO_CALL"  # Insufficient data.


@dataclass
class PricePoint:
    recorded_at: datetime
    price_usd: Decimal
    days_until_departure: int | None


@dataclass
class PriceHistoryStats:
    """Aggregated summary handed to `recommend_booking_window`."""

    sample_count: int                          # 0 = no history
    current_price: Decimal | None              # the live cheapest price (optional)
    median_price: Decimal | None
    min_price: Decimal | None
    max_price: Decimal | None
    current_pct_above_median: float | None     # negative = below median, good
    history: list[PricePoint] = field(default_factory=list)


@dataclass
class Recommendation:
    verdict: Verdict
    confidence: float                          # 0.0–1.0
    reasoning: str                             # Human-readable explanation
    median_price: Decimal | None = None
    current_pct_above_median: float | None = None
    sample_count: int = 0


# =============================================================================
# 🎯 HOOK 2 — IMPLEMENT THIS
# =============================================================================

def recommend_booking_window(
    stats: PriceHistoryStats,
    *,
    days_until_departure: int,
) -> Recommendation:
    """Decide whether to book now, wait, or stay neutral.

    Policy (per FlightDeck owner):
      • <10 samples → TOO_CLOSE_TO_CALL.  10–24 samples → confidence cap 0.5.
        ≥25 → 0.7.
      • <7 days + below median → BUY_NOW (highest priority; never demoted).
      • Base BUY_NOW: ≤-10% vs median AND trend ≠ falling.
      • Base WAIT: ≥+15% vs median AND >30 days out.
      • <14 days → never WAIT (convert to NEUTRAL — last-minute fares only rise).
      • Rising trend (last 7d) AND <30 days → bump NEUTRAL to BUY_NOW.
      • Falling trend AND BUY_NOW (and not the <7d override) → demote to NEUTRAL.
    """
    # 1. Sample-count guardrail
    if stats.sample_count < 10:
        return Recommendation(
            verdict=Verdict.TOO_CLOSE_TO_CALL,
            confidence=0.0,
            reasoning=(
                f"Only {stats.sample_count} price samples — need at least 10 for any verdict. "
                "Run `flightdeck scrape route` daily for ~10 days to build history."
            ),
            sample_count=stats.sample_count,
        )

    base_confidence = 0.7 if stats.sample_count >= 25 else 0.5
    trend = trend_direction(stats.history)
    median = stats.median_price
    pct = stats.current_pct_above_median

    # 2. No current price → can't compute a verdict; share what we know.
    if pct is None or stats.current_price is None:
        return Recommendation(
            verdict=Verdict.NEUTRAL,
            confidence=base_confidence * 0.5,
            reasoning=(
                f"{stats.sample_count} samples observed (median "
                f"${float(median):,.0f}, trend {trend}). "
                "Pass --current-price to compare against and unlock an actionable verdict."
            ),
            median_price=median,
            sample_count=stats.sample_count,
        )

    # 3. Highest-priority override: <7 days + below median → always BUY_NOW
    if days_until_departure < 7 and pct < 0:
        return Recommendation(
            verdict=Verdict.BUY_NOW,
            confidence=min(base_confidence + 0.1, 0.9),
            reasoning=(
                f"Less than a week out at {pct:+.1f}% vs median — "
                "last-minute deals are rare and disappear fast. Lock it in."
            ),
            median_price=median,
            current_pct_above_median=pct,
            sample_count=stats.sample_count,
        )

    # 4. Base verdict from price + trend
    if pct <= -10 and trend != "falling":
        verdict = Verdict.BUY_NOW
        reasoning = (
            f"{pct:+.1f}% below median (${float(median):,.0f}) and trend is {trend} — "
            "looks like a price bottom."
        )
    elif pct >= 15 and days_until_departure > 30:
        verdict = Verdict.WAIT
        reasoning = (
            f"{pct:+.1f}% above median (${float(median):,.0f}) with {days_until_departure} "
            f"days runway — prices likely to come down."
        )
    else:
        verdict = Verdict.NEUTRAL
        reasoning = (
            f"Current price {pct:+.1f}% vs median (${float(median):,.0f}); trend {trend}. "
            "No strong signal either way."
        )

    confidence = base_confidence

    # 5. Edge rules — order matters: WAIT-block first, then trend modifiers.

    # 5a. Near-departure WAIT-block: <14 days → never WAIT
    if verdict == Verdict.WAIT and days_until_departure < 14:
        verdict = Verdict.NEUTRAL
        reasoning += f" But only {days_until_departure} days out — last-minute fares typically only rise, so don't gamble."

    # 5b. Falling-trend caution: demote BUY_NOW to NEUTRAL
    if verdict == Verdict.BUY_NOW and trend == "falling":
        verdict = Verdict.NEUTRAL
        reasoning += " Trend is still falling though — watch a few more days, it could drop further."
        confidence = max(confidence - 0.1, 0.2)

    # 5c. Rising-trend urgency: NEUTRAL + rising + <30 days → BUY_NOW
    if verdict == Verdict.NEUTRAL and trend == "rising" and days_until_departure < 30:
        verdict = Verdict.BUY_NOW
        reasoning = (
            f"Prices rising over last 7 days with {days_until_departure} days "
            f"to departure — book before it gets worse."
        )

    return Recommendation(
        verdict=verdict,
        confidence=max(0.1, min(confidence, 0.9)),
        reasoning=reasoning,
        median_price=median,
        current_pct_above_median=pct,
        sample_count=stats.sample_count,
    )


# =============================================================================
# Helpers — feel free to use these in your implementation, or write your own.
# =============================================================================


def recent_average(history: list[PricePoint], days: int = 7) -> Decimal | None:
    """Mean price over the most-recent `days` window."""
    if not history:
        return None
    latest = history[-1].recorded_at
    cutoff_ts = latest.timestamp() - days * 86400
    recent = [p for p in history if p.recorded_at.timestamp() >= cutoff_ts]
    if not recent:
        return None
    total = sum(float(p.price_usd) for p in recent)
    return Decimal(str(total / len(recent)))


def trend_direction(history: list[PricePoint], window_days: int = 7) -> str:
    """Compare last-window mean to prior-window mean. Returns 'rising' | 'falling' | 'stable'."""
    if len(history) < 4:
        return "stable"
    latest = history[-1].recorded_at
    cutoff_recent = latest.timestamp() - window_days * 86400
    cutoff_prior = latest.timestamp() - 2 * window_days * 86400
    recent = [p for p in history if p.recorded_at.timestamp() >= cutoff_recent]
    prior = [p for p in history if cutoff_prior <= p.recorded_at.timestamp() < cutoff_recent]
    if not recent or not prior:
        return "stable"
    recent_avg = sum(float(p.price_usd) for p in recent) / len(recent)
    prior_avg = sum(float(p.price_usd) for p in prior) / len(prior)
    delta_pct = (recent_avg - prior_avg) / prior_avg * 100.0
    if delta_pct > 3:
        return "rising"
    if delta_pct < -3:
        return "falling"
    return "stable"
