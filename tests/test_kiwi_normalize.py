"""Tests for Kiwi Tequila offer normalization."""
from datetime import timedelta
from decimal import Decimal

from app.integrations.kiwi import _normalize_offer


SAMPLE_OFFER = {
    "id": "abc123",
    "price": 612.50,
    "deep_link": "https://www.kiwi.com/booking?token=...",
    "virtual_interlining": False,
    "route": [
        {
            "airline": "OZ",
            "flight_no": 201,
            "flyFrom": "SFO",
            "flyTo": "ICN",
            "local_departure": "2026-06-15T08:00:00.000Z",
            "local_arrival": "2026-06-16T13:00:00.000Z",
        },
        {
            "airline": "OZ",
            "flight_no": 104,
            "flyFrom": "ICN",
            "flyTo": "NRT",
            "local_departure": "2026-06-16T15:00:00.000Z",
            "local_arrival": "2026-06-16T17:10:00.000Z",
        },
    ],
}


def test_normalize_one_stop():
    offer = _normalize_offer(SAMPLE_OFFER)
    assert offer.source == "kiwi"
    assert offer.source_id == "abc123"
    assert offer.price_usd == Decimal("612.50")
    assert offer.stops == 1
    assert offer.fare_type == "regular"
    assert len(offer.segments) == 2
    assert offer.segments[0].origin == "SFO"
    assert offer.segments[1].destination == "NRT"
    assert offer.deep_link == "https://www.kiwi.com/booking?token=..."


def test_virtual_interlining_marks_self_transfer():
    raw = {**SAMPLE_OFFER, "virtual_interlining": True}
    offer = _normalize_offer(raw)
    assert offer.fare_type == "self_transfer"


def test_normalize_dedup_key_matches_amadeus():
    """A flight from Kiwi and the same flight from Amadeus should produce the same dedup_key."""
    offer = _normalize_offer({
        "id": "x",
        "price": 800,
        "route": [
            {
                "airline": "UA",
                "flight_no": 837,
                "flyFrom": "SFO",
                "flyTo": "NRT",
                "local_departure": "2026-06-15T11:00:00.000Z",
                "local_arrival": "2026-06-16T15:30:00.000Z",
            }
        ],
    })
    assert offer.dedup_key == "UA837@2026-06-15T11:00"
