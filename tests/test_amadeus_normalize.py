"""Tests for the pure (no-network) helpers in app.integrations.amadeus."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.integrations.amadeus import _normalize_offer, _parse_iso8601_duration


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("PT0M", timedelta()),
        ("PT35M", timedelta(minutes=35)),
        ("PT12H", timedelta(hours=12)),
        ("PT12H35M", timedelta(hours=12, minutes=35)),
        ("PT1H5M30S", timedelta(hours=1, minutes=5, seconds=30)),
        ("P1DT2H", timedelta(days=1, hours=2)),
    ],
)
def test_parse_iso8601_duration(raw, expected):
    assert _parse_iso8601_duration(raw) == expected


def test_parse_iso8601_duration_invalid():
    with pytest.raises(ValueError):
        _parse_iso8601_duration("12H35M")


# Minimal Amadeus offer fixture matching their public schema. One non-stop
# itinerary, one segment, one passenger.
SAMPLE_OFFER = {
    "id": "1",
    "price": {"currency": "USD", "grandTotal": "892.40", "total": "892.40"},
    "itineraries": [
        {
            "duration": "PT11H30M",
            "segments": [
                {
                    "id": "1",
                    "departure": {"iataCode": "SFO", "at": "2026-06-15T11:00:00"},
                    "arrival": {"iataCode": "NRT", "at": "2026-06-16T15:30:00"},
                    "carrierCode": "UA",
                    "number": "837",
                    "duration": "PT11H30M",
                },
            ],
        }
    ],
    "travelerPricings": [
        {"fareDetailsBySegment": [{"segmentId": "1", "cabin": "ECONOMY"}]}
    ],
}


def test_normalize_single_segment_offer():
    offer = _normalize_offer(SAMPLE_OFFER)
    assert offer.source == "amadeus"
    assert offer.source_id == "1"
    assert offer.price_usd == Decimal("892.40")
    assert offer.currency == "USD"
    assert offer.total_duration == timedelta(hours=11, minutes=30)
    assert offer.stops == 0
    assert len(offer.segments) == 1

    seg = offer.segments[0]
    assert seg.carrier == "UA"
    assert seg.flight_no == "837"
    assert seg.origin == "SFO"
    assert seg.destination == "NRT"
    assert seg.cabin == "economy"


def test_normalize_offer_dedup_key_stable():
    """Same flight from two calls should produce the same dedup key."""
    a = _normalize_offer(SAMPLE_OFFER)
    b = _normalize_offer(SAMPLE_OFFER)
    assert a.dedup_key == b.dedup_key
    assert a.dedup_key.startswith("UA837@")


def test_normalize_one_stop_offer():
    """An itinerary with two segments should produce stops=1."""
    raw = {
        "id": "2",
        "price": {"currency": "USD", "grandTotal": "612.00"},
        "itineraries": [
            {
                "duration": "PT13H10M",
                "segments": [
                    {
                        "id": "1",
                        "departure": {"iataCode": "SFO", "at": "2026-06-15T08:00:00"},
                        "arrival": {"iataCode": "ICN", "at": "2026-06-16T13:00:00"},
                        "carrierCode": "OZ",
                        "number": "201",
                        "duration": "PT12H",
                    },
                    {
                        "id": "2",
                        "departure": {"iataCode": "ICN", "at": "2026-06-16T15:00:00"},
                        "arrival": {"iataCode": "NRT", "at": "2026-06-16T17:10:00"},
                        "carrierCode": "OZ",
                        "number": "104",
                        "duration": "PT2H10M",
                    },
                ],
            }
        ],
        "travelerPricings": [],
    }
    offer = _normalize_offer(raw)
    assert offer.stops == 1
    assert len(offer.segments) == 2
    assert offer.segments[0].destination == offer.segments[1].origin == "ICN"
