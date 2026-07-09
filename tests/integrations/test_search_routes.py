"""Route-level tests for /api/v1/routes/search — hits the real FastAPI app + DB session,
not just schemas or pure functions.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.models import FlightOffer, Search


async def _post_search(client, **overrides) -> dict:
    body = {
        "origin": "SFO",
        "destination": "NRT",
        "departure_date": "2027-03-01",
        **overrides,
    }
    resp = await client.post("/api/v1/routes/search", json=body)
    assert resp.status_code == 200
    return resp.json()


async def test_search_persists_and_returns_empty_offers(client, db_session):
    body = await _post_search(client)
    assert body["origin"] == "SFO"
    assert body["destination"] == "NRT"
    assert body["departure_date"] == "2027-03-01"
    assert body["offer_count"] == 0
    assert body["offers"] == []

    search_id = body["search_id"]
    search = await db_session.get(Search, search_id)
    assert search is not None
    assert search.origin == "SFO"
    assert search.destination == "NRT"


async def test_search_echoes_return_date(client):
    body = await _post_search(client, return_date="2027-03-10")
    assert body["return_date"] == "2027-03-10"


async def test_search_rejects_bad_origin_length(client):
    resp = await client.post(
        "/api/v1/routes/search",
        json={"origin": "SF", "destination": "NRT", "departure_date": "2027-03-01"},
    )
    assert resp.status_code == 422


async def test_get_results_unknown_search_404s(client):
    resp = await client.get(f"/api/v1/routes/search/{uuid4()}/results")
    assert resp.status_code == 404


async def test_get_results_empty_when_no_offers(client):
    body = await _post_search(client)
    search_id = body["search_id"]

    resp = await client.get(f"/api/v1/routes/search/{search_id}/results")
    assert resp.status_code == 200
    result = resp.json()
    assert result["offer_count"] == 0
    assert result["offers"] == []


def _segment(origin: str, destination: str) -> dict:
    return {
        "carrier": "UA",
        "flight_no": "UA123",
        "origin": origin,
        "destination": destination,
        "depart_at": "2027-03-01T08:00:00",
        "arrive_at": "2027-03-01T12:00:00",
        "duration_seconds": 14400,
        "cabin": "economy",
    }


async def test_get_results_sorting(client, db_session):
    body = await _post_search(client)
    search_id = body["search_id"]

    offers = [
        FlightOffer(
            search_id=search_id,
            source="amadeus",
            price_usd=Decimal("900.00"),
            currency="USD",
            total_duration=timedelta(hours=10),
            stops=2,
            segments=[_segment("SFO", "NRT")],
            fare_type="regular",
        ),
        FlightOffer(
            search_id=search_id,
            source="kiwi",
            price_usd=Decimal("400.00"),
            currency="USD",
            total_duration=timedelta(hours=15),
            stops=0,
            segments=[_segment("SFO", "NRT")],
            fare_type="regular",
        ),
        FlightOffer(
            search_id=search_id,
            source="serpapi",
            price_usd=Decimal("650.00"),
            currency="USD",
            total_duration=timedelta(hours=8),
            stops=1,
            segments=[_segment("SFO", "NRT")],
            fare_type="regular",
        ),
    ]
    for o in offers:
        db_session.add(o)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/routes/search/{search_id}/results", params={"sort_by": "price"}
    )
    assert resp.status_code == 200
    prices = [Decimal(o["price_usd"]) for o in resp.json()["offers"]]
    assert prices == sorted(prices)
    assert prices[0] == Decimal("400.00")

    resp = await client.get(
        f"/api/v1/routes/search/{search_id}/results", params={"sort_by": "duration"}
    )
    assert resp.status_code == 200
    durations = [o["total_duration"] for o in resp.json()["offers"]]
    # shortest duration (8h) first
    assert durations[0] == "PT8H"

    resp = await client.get(
        f"/api/v1/routes/search/{search_id}/results", params={"sort_by": "stops"}
    )
    assert resp.status_code == 200
    stops = [o["stops"] for o in resp.json()["offers"]]
    assert stops == sorted(stops)
    assert stops[0] == 0


async def test_get_results_respects_limit(client, db_session):
    body = await _post_search(client)
    search_id = body["search_id"]

    for i in range(3):
        db_session.add(
            FlightOffer(
                search_id=search_id,
                source="amadeus",
                price_usd=Decimal(f"{100 + i}.00"),
                currency="USD",
                total_duration=timedelta(hours=5 + i),
                stops=0,
                segments=[_segment("SFO", "NRT")],
                fare_type="regular",
            )
        )
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/routes/search/{search_id}/results", params={"limit": 2}
    )
    assert resp.status_code == 200
    assert len(resp.json()["offers"]) == 2

    stmt = select(FlightOffer).where(FlightOffer.search_id == search_id)
    all_offers = (await db_session.execute(stmt)).scalars().all()
    assert len(all_offers) == 3
