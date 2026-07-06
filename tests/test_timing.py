"""Tests for `recommend_booking_window` — Hook 2 user contribution.

The default stub returns NEUTRAL when there's any history, TOO_CLOSE_TO_CALL
when there's none. These tests pass against the default. As you add logic,
turn the marked tests into the behavior you want.

xfail markers describe behaviors you'll likely want to implement. Remove them
as you implement each.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.services.timing import (
    PriceHistoryStats,
    PricePoint,
    Recommendation,
    Verdict,
    recent_average,
    recommend_booking_window,
    trend_direction,
)


def make_history(prices: list[float], days_back_per_point: int = 1) -> list[PricePoint]:
    """Build a price-history list from a price array, oldest first.

    `days_back_per_point` controls spacing — default 1 day apart.
    """
    base = datetime.now(UTC) - timedelta(days=len(prices) * days_back_per_point)
    return [
        PricePoint(
            recorded_at=base + timedelta(days=i * days_back_per_point),
            price_usd=Decimal(str(p)),
            days_until_departure=60 - i,  # arbitrary
        )
        for i, p in enumerate(prices)
    ]


def stats_from(prices: list[float], current: float | None) -> PriceHistoryStats:
    history = make_history(prices)
    sorted_p = sorted(prices)
    n = len(sorted_p)
    median = sorted_p[n // 2] if n % 2 == 1 else (sorted_p[n // 2 - 1] + sorted_p[n // 2]) / 2 if n else None
    cur_pct = ((current - median) / median * 100) if (current is not None and median) else None
    return PriceHistoryStats(
        sample_count=n,
        current_price=Decimal(str(current)) if current is not None else None,
        median_price=Decimal(str(median)) if median else None,
        min_price=Decimal(str(min(prices))) if prices else None,
        max_price=Decimal(str(max(prices))) if prices else None,
        current_pct_above_median=cur_pct,
        history=history,
    )


# --- Default-stub-passes tests -----------------------------------------------

def test_no_history_returns_too_close_to_call():
    stats = PriceHistoryStats(0, None, None, None, None, None, [])
    rec = recommend_booking_window(stats, days_until_departure=30)
    assert rec.verdict == Verdict.TOO_CLOSE_TO_CALL


def test_recommendation_has_reasoning_string():
    stats = stats_from([800, 850, 900], current=825)
    rec = recommend_booking_window(stats, days_until_departure=45)
    assert isinstance(rec.reasoning, str)
    assert len(rec.reasoning) > 0


# --- Behavior the user will implement ----------------------------------------


def test_few_samples_returns_too_close_to_call():
    """With <10 samples, the recommendation must be TOO_CLOSE_TO_CALL."""
    stats = stats_from([800, 850, 900], current=825)
    rec = recommend_booking_window(stats, days_until_departure=45)
    assert rec.verdict == Verdict.TOO_CLOSE_TO_CALL
    assert rec.confidence == 0.0


def test_below_25_samples_caps_confidence_at_05():
    """With 10–24 samples, confidence is capped at 0.5."""
    stats = stats_from([800] * 15, current=720)  # 10% below median
    rec = recommend_booking_window(stats, days_until_departure=45)
    assert rec.confidence <= 0.5


def test_at_least_25_samples_allows_07_confidence():
    """≥25 samples → confidence floor is 0.7 for confident verdicts."""
    stats = stats_from([900] * 30, current=750)  # ~17% below median
    rec = recommend_booking_window(stats, days_until_departure=45)
    assert rec.verdict == Verdict.BUY_NOW
    assert rec.confidence >= 0.7


def test_well_below_median_with_stable_trend_says_buy_now():
    """Current price 17% below median, healthy sample count, stable trend → BUY_NOW."""
    prices = [900] * 30
    stats = stats_from(prices, current=750)
    rec = recommend_booking_window(stats, days_until_departure=45)
    assert rec.verdict == Verdict.BUY_NOW
    assert rec.confidence >= 0.7


def test_well_above_median_far_out_says_wait():
    """At 75 days out and 25% above median → WAIT."""
    prices = [800] * 30
    stats = stats_from(prices, current=1000)
    rec = recommend_booking_window(stats, days_until_departure=75)
    assert rec.verdict == Verdict.WAIT


def test_close_to_departure_neutral_or_buy():
    """At 7 days out, prices typically only go up — should not say WAIT."""
    prices = [800] * 30
    stats = stats_from(prices, current=900)  # slightly above
    rec = recommend_booking_window(stats, days_until_departure=7)
    assert rec.verdict != Verdict.WAIT


# --- Edge rules --------------------------------------------------------------

def test_near_departure_buy_bias_overrides_everything():
    """<7 days + below median → BUY_NOW even if trend is falling."""
    base = datetime.now(UTC) - timedelta(days=14)
    history = []
    # Build a price history that is clearly falling
    for i, p in enumerate([1000, 1000, 1000, 950, 950, 950, 900, 900, 900, 850, 850, 850]):
        history.append(PricePoint(
            recorded_at=base + timedelta(days=i),
            price_usd=Decimal(str(p)),
            days_until_departure=None,
        ))
    stats = PriceHistoryStats(
        sample_count=12,
        current_price=Decimal("800"),  # below the median (~925)
        median_price=Decimal("925"),
        min_price=Decimal("850"),
        max_price=Decimal("1000"),
        current_pct_above_median=-13.5,
        history=history,
    )
    rec = recommend_booking_window(stats, days_until_departure=5)
    assert rec.verdict == Verdict.BUY_NOW


def test_wait_block_within_14_days_demotes_to_neutral():
    """+25% above median but only 10 days out → must NOT be WAIT.

    The WAIT-block edge rule combined with the base WAIT condition (>30 days)
    means we never WAIT inside the 14-day window. The verdict is NEUTRAL.
    """
    prices = [800] * 30
    stats = stats_from(prices, current=1000)  # +25%
    rec = recommend_booking_window(stats, days_until_departure=10)
    assert rec.verdict != Verdict.WAIT
    assert rec.verdict == Verdict.NEUTRAL


def test_falling_trend_demotes_buy_now_to_neutral():
    """Below-median + falling trend → demote BUY_NOW to NEUTRAL (be patient)."""
    base = datetime.now(UTC) - timedelta(days=20)
    # Clearly falling: 1000 → 850 over the window
    prices = [1000, 1000, 1000, 1000, 1000, 950, 950, 950, 950, 950,
              900, 900, 900, 900, 900, 850, 850, 850, 850, 850]
    history = [
        PricePoint(
            recorded_at=base + timedelta(days=i),
            price_usd=Decimal(str(p)),
            days_until_departure=None,
        )
        for i, p in enumerate(prices)
    ]
    stats = PriceHistoryStats(
        sample_count=20,
        current_price=Decimal("820"),  # below median
        median_price=Decimal("925"),
        min_price=Decimal("850"),
        max_price=Decimal("1000"),
        current_pct_above_median=-11.4,
        history=history,
    )
    rec = recommend_booking_window(stats, days_until_departure=45)
    assert rec.verdict == Verdict.NEUTRAL
    assert "fall" in rec.reasoning.lower()


def test_rising_trend_promotes_neutral_to_buy_now():
    """Near-median price + rising trend + <30 days out → demote NEUTRAL to BUY_NOW."""
    base = datetime.now(UTC) - timedelta(days=20)
    # Clearly rising: 800 → 950 over the window
    prices = [800, 800, 800, 800, 800, 850, 850, 850, 850, 850,
              900, 900, 900, 900, 900, 950, 950, 950, 950, 950]
    history = [
        PricePoint(
            recorded_at=base + timedelta(days=i),
            price_usd=Decimal(str(p)),
            days_until_departure=None,
        )
        for i, p in enumerate(prices)
    ]
    stats = PriceHistoryStats(
        sample_count=20,
        current_price=Decimal("920"),  # near median, slightly above
        median_price=Decimal("875"),
        min_price=Decimal("800"),
        max_price=Decimal("950"),
        current_pct_above_median=5.1,  # only +5%, not enough for WAIT
        history=history,
    )
    rec = recommend_booking_window(stats, days_until_departure=20)
    assert rec.verdict == Verdict.BUY_NOW
    assert "rising" in rec.reasoning.lower() or "before it gets worse" in rec.reasoning.lower()


def test_no_current_price_returns_neutral_with_low_confidence():
    """Without a current_price to compare, return NEUTRAL with halved confidence."""
    stats = stats_from([900] * 30, current=None)
    rec = recommend_booking_window(stats, days_until_departure=45)
    assert rec.verdict == Verdict.NEUTRAL
    assert rec.confidence < 0.5


# --- Helpers (already work) --------------------------------------------------


def test_recent_average_window():
    history = make_history([700, 800, 900, 1000], days_back_per_point=2)
    avg = recent_average(history, days=5)
    # The last 3 points are within 5 days back; their mean is (800+900+1000)/3 = 900
    assert avg == pytest.approx(Decimal("900"))


def test_recent_average_empty():
    assert recent_average([]) is None


def test_trend_direction_rising():
    """Two windows: prior=[800,800,800], recent=[900,900,900]"""
    base = datetime.now(UTC) - timedelta(days=14)
    history = []
    for i, p in enumerate([800, 800, 800, 900, 900, 900]):
        history.append(PricePoint(
            recorded_at=base + timedelta(days=i * 2),
            price_usd=Decimal(str(p)),
            days_until_departure=None,
        ))
    assert trend_direction(history, window_days=6) == "rising"


def test_trend_direction_falling():
    base = datetime.now(UTC) - timedelta(days=14)
    history = []
    for i, p in enumerate([900, 900, 900, 800, 800, 800]):
        history.append(PricePoint(
            recorded_at=base + timedelta(days=i * 2),
            price_usd=Decimal(str(p)),
            days_until_departure=None,
        ))
    assert trend_direction(history, window_days=6) == "falling"


def test_trend_direction_stable_with_thin_data():
    """3 points → not enough history to compute a trend."""
    history = make_history([800, 800, 800])
    assert trend_direction(history) == "stable"
