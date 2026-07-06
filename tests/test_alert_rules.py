"""Tests for `evaluate_watch` — Hook 4 (implemented policy).

Policy: TARGET_HIT > PRICE_DROP (≥10%) > NEW_LOW (≥3% under all-time low)
> PRICE_SPIKE (≥20% rise inside 21 days). Downward alerts share a 2%
re-alert debounce; spikes are time-debounced (24h).
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.alert_rules import (
    AlertDecision,
    AlertKind,
    PriceObservation,
    WatchSnapshot,
    evaluate_watch,
)

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def obs(price: str, source: str = "amadeus") -> PriceObservation:
    return PriceObservation(price_usd=Decimal(price), source=source, observed_at=NOW)


def snap(
    *,
    target: str | None = None,
    last: str | None = None,
    lowest: str | None = None,
    last_alerted: str | None = None,
    alerted_hours_ago: int | None = None,
    days_out: int = 90,
) -> WatchSnapshot:
    return WatchSnapshot(
        target_price_usd=Decimal(target) if target else None,
        last_price_usd=Decimal(last) if last else None,
        lowest_seen_usd=Decimal(lowest) if lowest else None,
        last_alerted_price_usd=Decimal(last_alerted) if last_alerted else None,
        last_alerted_at=(
            NOW - timedelta(hours=alerted_hours_ago) if alerted_hours_ago else None
        ),
        days_until_departure=days_out,
    )


# --- Default-stub-passes tests -----------------------------------------------


def test_returns_decision():
    d = evaluate_watch(obs("700"), snap(target="800"))
    assert isinstance(d, AlertDecision)


def test_target_hit_fires():
    d = evaluate_watch(obs("700"), snap(target="800", last="900", lowest="900"))
    assert d.fire
    assert d.kind == AlertKind.TARGET_HIT
    assert d.message


def test_above_target_does_not_fire():
    d = evaluate_watch(obs("850"), snap(target="800", last="900", lowest="850"))
    assert not d.fire


def test_no_target_no_history_does_not_fire():
    """First-ever observation with no target: nothing to compare against."""
    d = evaluate_watch(obs("700"), snap())
    assert not d.fire


def test_target_hit_debounces_same_price():
    """Already alerted at $750 — re-observing $750 is not news."""
    d = evaluate_watch(
        obs("750"),
        snap(target="800", last="750", lowest="750",
             last_alerted="750", alerted_hours_ago=6),
    )
    assert not d.fire


def test_target_hit_refires_on_further_drop():
    """Alerted at $750, now $650 — that IS news."""
    d = evaluate_watch(
        obs("650"),
        snap(target="800", last="750", lowest="750",
             last_alerted="750", alerted_hours_ago=6),
    )
    assert d.fire


# --- Zero-config signals ------------------------------------------------------


def test_big_drop_without_target_fires():
    """No target set, but the fare fell 25% since last check — that's news."""
    d = evaluate_watch(obs("600"), snap(last="800", lowest="780"))
    assert d.fire
    assert d.kind == AlertKind.PRICE_DROP


def test_small_jitter_without_target_does_not_fire():
    """A 2% wobble between checks is API noise, not a deal."""
    d = evaluate_watch(obs("784"), snap(last="800", lowest="780"))
    assert not d.fire


def test_new_low_fires_without_target():
    """Cheapest ever seen for this trip (with real history behind it)."""
    d = evaluate_watch(obs("640"), snap(last="720", lowest="700"))
    assert d.fire
    assert d.kind in (AlertKind.NEW_LOW, AlertKind.PRICE_DROP)


def test_refire_requires_meaningful_improvement():
    """Alerted at $750; $748 (-0.3%) should stay quiet even though it's lower."""
    d = evaluate_watch(
        obs("748"),
        snap(target="800", last="750", lowest="750",
             last_alerted="750", alerted_hours_ago=6),
    )
    assert not d.fire


def test_pure_new_low_without_big_step():
    """Modest step from last check (-4%) but 3%+ under the all-time low."""
    d = evaluate_watch(obs("650"), snap(last="678", lowest="700"))
    assert d.fire
    assert d.kind == AlertKind.NEW_LOW


# --- Spike path ----------------------------------------------------------------


def test_spike_near_departure_fires():
    """+25% two weeks out — book-now warning."""
    d = evaluate_watch(obs("1000"), snap(last="800", lowest="750", days_out=14))
    assert d.fire
    assert d.kind == AlertKind.PRICE_SPIKE


def test_spike_far_from_departure_stays_quiet():
    """Same +25%, but 200 days out — fares wobble; not actionable."""
    d = evaluate_watch(obs("1000"), snap(last="800", lowest="750", days_out=200))
    assert not d.fire


def test_spike_respects_cooldown():
    """Already alerted 6h ago — don't spam a second spike warning."""
    d = evaluate_watch(
        obs("1000"),
        snap(last="800", lowest="750", days_out=14,
             last_alerted="780", alerted_hours_ago=6),
    )
    assert not d.fire


# --- Sanity ------------------------------------------------------------------


def test_alert_kinds_are_distinct_strings():
    values = [k.value for k in AlertKind]
    assert len(values) == len(set(values))
