"""Route-level tests for /api/v1/offers/{offer_id}/booking — hits the real
FastAPI app + DB session, not just schemas or pure functions.
"""
from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.models import Airline, FlightOffer, Search


async def _create_search(db_session, **overrides) -> Search:
    search = Search(
        origin="SFO",
        destination="NRT",
        departure_date=overrides.pop("departure_date", None),
        return_date=overrides.pop("return_date", None),
        cabin_class="economy",
        **overrides,
    )
    db_session.add(search)
    await db_session.commit()
    await db_session.refresh(search)
    return search


async def _create_offer(db_session, **overrides) -> FlightOffer:
    segments = overrides.pop(
        "segments",
        [
            {
                "carrier": "UA",
                "flight_no": "837",
                "origin": "SFO",
                "destination": "NRT",
                "depart_at": "2027-03-01T10:00:00",
                "arrive_at": "2027-03-02T14:00:00",
                "duration": "PT11H",
                "cabin": "economy",
            }
        ],
    )
    defaults = {"source": "kiwi", "price_usd": 725}
    defaults.update(overrides)
    offer = FlightOffer(segments=segments, **defaults)
    db_session.add(offer)
    await db_session.commit()
    await db_session.refresh(offer)
    return offer


async def _get_or_create_airline(db_session, iata_code: str, **overrides) -> Airline:
    airline = await db_session.get(Airline, iata_code)
    if airline is not None:
        for key, value in overrides.items():
            setattr(airline, key, value)
        await db_session.commit()
        await db_session.refresh(airline)
        return airline
    airline = Airline(iata_code=iata_code, **overrides)
    db_session.add(airline)
    await db_session.commit()
    await db_session.refresh(airline)
    return airline


async def test_offer_booking_links_with_search_and_airline(client, db_session):
    search = await _create_search(db_session, departure_date=date(2027, 3, 1))
    await _get_or_create_airline(
        db_session,
        "UA",
        name="United Airlines",
        direct_booking_url="https://www.united.com",
        loyalty_program="MileagePlus",
    )

    offer = await _create_offer(
        db_session,
        search_id=search.id,
        deep_link="https://kiwi.com/deal/123",
    )

    resp = await client.get(f"/api/v1/offers/{offer.id}/booking")
    assert resp.status_code == 200
    body = resp.json()

    assert "SFO" in body["context"]
    assert "NRT" in body["context"]
    assert "kiwi" in body["context"]
    assert float(body["price_usd"]) == 725.0

    kinds = [link["kind"] for link in body["links"]]
    assert kinds == ["airline_direct", "source", "google_flights"]

    airline_link = body["links"][0]
    assert airline_link["url"] == "https://www.united.com"
    assert "MileagePlus" in airline_link["note"]

    source_link = body["links"][1]
    assert source_link["url"] == "https://kiwi.com/deal/123"

    google_link = body["links"][2]
    assert "SFO" in google_link["url"]
    assert "NRT" in google_link["url"]


async def test_offer_booking_links_without_search_falls_back_to_segments(client, db_session):
    # ZZ is not a seeded airline code, so no airline_direct link should appear.
    segments = [
        {
            "carrier": "ZZ",
            "flight_no": "1",
            "origin": "SFO",
            "destination": "NRT",
            "depart_at": "2027-03-01T10:00:00",
            "arrive_at": "2027-03-02T14:00:00",
            "duration": "PT11H",
            "cabin": "economy",
        }
    ]
    offer = await _create_offer(
        db_session, source="amadeus", price_usd=999, segments=segments
    )

    resp = await client.get(f"/api/v1/offers/{offer.id}/booking")
    assert resp.status_code == 200
    body = resp.json()

    assert "SFO" in body["context"]
    assert "NRT" in body["context"]
    assert "amadeus" in body["context"]
    # no airline row and no deep_link/booking_url -> only google_flights link
    kinds = [link["kind"] for link in body["links"]]
    assert kinds == ["google_flights"]


async def test_offer_booking_links_unknown_offer_404s(client):
    resp = await client.get(f"/api/v1/offers/{uuid4()}/booking")
    assert resp.status_code == 404


async def test_offer_booking_links_invalid_uuid_422s(client):
    resp = await client.get("/api/v1/offers/not-a-uuid/booking")
    assert resp.status_code == 422
