"""Tests for offer deduplication across sources."""
from datetime import datetime, timedelta
from decimal import Decimal

from app.integrations.types import NormalizedOffer, Segment
from app.services.dedup import dedupe_offers


def _offer(source: str, price: float, flight_no: str = "100", source_id: str = "x") -> NormalizedOffer:
    depart = datetime(2026, 6, 15, 11, 0)
    return NormalizedOffer(
        source=source,
        source_id=source_id,
        price_usd=Decimal(str(price)),
        currency="USD",
        total_duration=timedelta(hours=11, minutes=30),
        stops=0,
        segments=[
            Segment(
                carrier="UA",
                flight_no=flight_no,
                origin="SFO",
                destination="NRT",
                depart_at=depart,
                arrive_at=depart + timedelta(hours=11, minutes=30),
                duration=timedelta(hours=11, minutes=30),
            )
        ],
    )


def test_dedup_keeps_cheapest_canonical():
    """Same flight from two sources at different prices → keep cheaper."""
    amadeus = _offer("amadeus", 950, source_id="a")
    kiwi = _offer("kiwi", 875, source_id="k")
    out = dedupe_offers([amadeus, kiwi])
    assert len(out) == 1
    assert out[0].offer.price_usd == Decimal("875")
    assert out[0].offer.source == "kiwi"
    assert set(out[0].sources) == {"amadeus", "kiwi"}
    assert out[0].all_prices == {"amadeus": 950.0, "kiwi": 875.0}


def test_dedup_treats_different_flights_as_distinct():
    """Different flight numbers on the same route → two rows, no merging."""
    flight_a = _offer("amadeus", 600, flight_no="100", source_id="a")
    flight_b = _offer("amadeus", 700, flight_no="200", source_id="b")
    out = dedupe_offers([flight_a, flight_b])
    assert len(out) == 2


def test_dedup_handles_empty_input():
    assert dedupe_offers([]) == []
