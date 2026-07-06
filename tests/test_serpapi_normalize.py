"""Tests for SerpAPI Google Flights offer normalization."""
from datetime import timedelta
from decimal import Decimal

from app.integrations.serpapi import _normalize_offer


SAMPLE_OFFER = {
    "price": 892,
    "total_duration": 690,  # 11h 30m
    "booking_token": "tok_abc",
    "flights": [
        {
            "departure_airport": {"id": "SFO", "time": "2026-06-15 11:00"},
            "arrival_airport": {"id": "NRT", "time": "2026-06-16 15:30"},
            "duration": 690,
            "flight_number": "UA 837",
            "travel_class": "Economy",
        }
    ],
}


def test_normalize_nonstop():
    offer = _normalize_offer(SAMPLE_OFFER)
    assert offer.source == "serpapi"
    assert offer.source_id == "tok_abc"
    assert offer.price_usd == Decimal("892")
    assert offer.stops == 0
    assert offer.total_duration == timedelta(minutes=690)
    assert len(offer.segments) == 1
    seg = offer.segments[0]
    assert seg.carrier == "UA"
    assert seg.flight_no == "837"
    assert seg.cabin == "economy"


def test_dedup_key_aligns_with_amadeus_kiwi():
    """All three sources should produce the same dedup_key for the same flight."""
    offer = _normalize_offer(SAMPLE_OFFER)
    assert offer.dedup_key == "UA837@2026-06-15T11:00"


def test_normalize_business_class():
    raw = {**SAMPLE_OFFER}
    raw["flights"] = [
        {**SAMPLE_OFFER["flights"][0], "travel_class": "Business"},
    ]
    offer = _normalize_offer(raw)
    assert offer.segments[0].cabin == "business"
