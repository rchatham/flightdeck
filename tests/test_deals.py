"""Tests for deal-scan helpers (pure functions — no DB, no network)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.deals import compute_median, deal_tier, sample_dates


def test_sample_dates_small_window_returns_every_day():
    days = sample_dates(date(2026, 9, 1), date(2026, 9, 5), max_n=10)
    assert days == [date(2026, 9, d) for d in (1, 2, 3, 4, 5)]


def test_sample_dates_caps_and_keeps_endpoints():
    days = sample_dates(date(2026, 9, 1), date(2026, 9, 30), max_n=4)
    assert len(days) == 4
    assert days[0] == date(2026, 9, 1)
    assert days[-1] == date(2026, 9, 30)
    assert days == sorted(days)


def test_sample_dates_single_slot():
    assert sample_dates(date(2026, 9, 1), date(2026, 9, 30), max_n=1) == [date(2026, 9, 1)]


def test_sample_dates_swapped_bounds():
    days = sample_dates(date(2026, 9, 5), date(2026, 9, 1), max_n=10)
    assert days[0] == date(2026, 9, 1) and days[-1] == date(2026, 9, 5)


def test_deal_tier_thresholds():
    assert deal_tier(-25.0) == "DEAL"
    assert deal_tier(-20.0) == "DEAL"
    assert deal_tier(-15.0) == "GOOD"
    assert deal_tier(-10.0) == "GOOD"
    assert deal_tier(-5.0) is None
    assert deal_tier(12.0) is None
    assert deal_tier(None) is None


def test_compute_median():
    assert compute_median([]) is None
    assert compute_median([Decimal("100")]) == Decimal("100.0")
    assert compute_median([Decimal("100"), Decimal("300")]) == Decimal("200.0")
    assert compute_median([Decimal("100"), Decimal("200"), Decimal("900")]) == Decimal("200.0")
