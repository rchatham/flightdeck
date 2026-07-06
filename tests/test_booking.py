"""Tests for the booking-handoff link builders (pure functions, no DB)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from app.models import Airline, FlightOffer, Search
from app.services.booking import (
    build_offer_links,
    build_route_links,
    google_flights_url,
)


def make_offer(**overrides) -> FlightOffer:
    defaults = dict(
        id=uuid4(),
        search_id=None,
        source="kiwi",
        price_usd=Decimal("750"),
        currency="USD",
        stops=0,
        segments=[
            {
                "carrier": "UA", "flight_no": "837", "origin": "SFO",
                "destination": "NRT", "depart_at": "2026-10-15T11:00:00",
                "arrive_at": "2026-10-16T14:30:00", "duration_seconds": 41400,
                "cabin": "economy",
            }
        ],
        fare_type="published",
        booking_url=None,
        deep_link="https://kiwi.example/deep/abc123",
    )
    defaults.update(overrides)
    return FlightOffer(**defaults)


def make_airline() -> Airline:
    return Airline(
        iata_code="UA",
        name="United Airlines",
        alliance="Star Alliance",
        is_regional=False,
        direct_booking_url="https://www.united.com",
        loyalty_program="MileagePlus",
    )


def test_google_flights_url_one_way():
    url = google_flights_url("SFO", "NRT", date(2026, 10, 15))
    parsed = urlparse(url)
    q = parse_qs(parsed.query)["q"][0]
    assert parsed.netloc == "www.google.com"
    assert q == "Flights from SFO to NRT on 2026-10-15"


def test_google_flights_url_round_trip():
    url = google_flights_url("SFO", "NRT", date(2026, 10, 15), date(2026, 10, 22))
    q = parse_qs(urlparse(url).query)["q"][0]
    assert "through 2026-10-22" in q


def test_route_links_for_watch():
    links = build_route_links("SFO", "NRT", date(2026, 10, 15))
    assert len(links) == 1
    assert links[0].kind == "google_flights"
    assert "SFO" in links[0].url


def test_offer_links_ordering_prefers_airline_direct():
    links = build_offer_links(make_offer(), airline=make_airline())
    kinds = [link.kind for link in links]
    assert kinds == ["airline_direct", "source", "google_flights"]
    assert links[0].url == "https://www.united.com"
    assert "MileagePlus" in links[0].note
    assert links[1].url == "https://kiwi.example/deep/abc123"


def test_offer_links_without_airline_or_deeplink():
    offer = make_offer(deep_link=None, booking_url=None)
    links = build_offer_links(offer, airline=None)
    assert [link.kind for link in links] == ["google_flights"]


def test_offer_links_fall_back_to_booking_url():
    offer = make_offer(deep_link=None, booking_url="https://ota.example/x")
    links = build_offer_links(offer, airline=None)
    assert links[0].kind == "source"
    assert links[0].url == "https://ota.example/x"


def test_offer_route_prefers_search_for_round_trip():
    """Round-trip segments end back at the origin; the Search row is truth."""
    search = Search(
        id=uuid4(), origin="SFO", destination="NRT",
        departure_date=date(2026, 10, 15), return_date=date(2026, 10, 22),
        flex_days=0, passengers=1, cabin_class="economy", include_nearby=True,
    )
    offer = make_offer(segments=[
        {"carrier": "UA", "origin": "SFO", "destination": "NRT",
         "depart_at": "2026-10-15T11:00:00"},
        {"carrier": "UA", "origin": "NRT", "destination": "SFO",
         "depart_at": "2026-10-22T17:00:00"},
    ])
    links = build_offer_links(offer, search=search)
    gf = next(link for link in links if link.kind == "google_flights")
    q = parse_qs(urlparse(gf.url).query)["q"][0]
    assert "from SFO to NRT" in q          # not "to SFO" from the last segment
    assert "through 2026-10-22" in q


def test_offer_links_empty_segments_no_crash():
    offer = make_offer(segments=[], deep_link=None, booking_url=None)
    assert build_offer_links(offer, airline=None) == []
