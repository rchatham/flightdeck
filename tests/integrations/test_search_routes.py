"""Route-level tests for /api/v1/routes/search — hits the real FastAPI app + DB session,
not just schemas or pure functions.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import redis.asyncio as redis_asyncio
from sqlalchemy import select

from app.api.schemas.search import SearchRequest
from app.config import get_settings
from app.integrations.types import NormalizedOffer, Segment
from app.models import FlightOffer, Search
from app.services.route_optimizer import _offers_cache_key


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


async def test_identical_search_second_call_served_from_cache(client):
    """Two identical searches should only fan out to providers once — the
    second is served from the Redis cache in `_fan_out_sources`.

    Providers aren't configured with API keys in dev, so both calls return
    empty offer lists regardless of caching; a call-counting mock on each
    provider search function is the only way to prove the second call didn't
    re-hit them.
    """
    body = {
        "origin": "LAX",
        "destination": "CDG",
        "departure_date": "2027-09-14",
        "include_nearby": False,
    }

    # Guard against a warm cache entry left over from a previous run of this
    # same test (Redis isn't reset between test runs like the DB is).
    cache_key = _offers_cache_key(SearchRequest(**body))
    redis_client = redis_asyncio.from_url(get_settings().redis_url)
    await redis_client.delete(cache_key)

    try:
        mock_amadeus = AsyncMock(return_value=[])
        mock_kiwi = AsyncMock(return_value=[])
        mock_serpapi = AsyncMock(return_value=[])
        with (
            patch("app.services.route_optimizer._search_amadeus", mock_amadeus),
            patch("app.services.route_optimizer._search_kiwi", mock_kiwi),
            patch("app.services.route_optimizer._search_serpapi", mock_serpapi),
        ):
            first = await client.post("/api/v1/routes/search", json=body)
            assert first.status_code == 200
            assert mock_amadeus.await_count == 1
            assert mock_kiwi.await_count == 1
            assert mock_serpapi.await_count == 1

            second = await client.post("/api/v1/routes/search", json=body)
            assert second.status_code == 200

            # Cache hit on the second call — providers weren't called again.
            assert mock_amadeus.await_count == 1
            assert mock_kiwi.await_count == 1
            assert mock_serpapi.await_count == 1
    finally:
        await redis_client.delete(cache_key)
        await redis_client.aclose()


def _fake_offer(source: str, origin: str, destination: str, price: str,
                 flight_no: str, depart_at: datetime) -> NormalizedOffer:
    return NormalizedOffer(
        source=source,
        source_id=f"{source}-{origin}-{destination}",
        price_usd=Decimal(price),
        currency="USD",
        total_duration=timedelta(hours=10),
        stops=0,
        segments=[Segment(
            carrier="UA", flight_no=flight_no, origin=origin, destination=destination,
            depart_at=depart_at, arrive_at=depart_at + timedelta(hours=10),
            duration=timedelta(hours=10),
        )],
    )


async def test_open_jaw_search_persists_return_leg_and_tags_offers(client, db_session):
    """SFO->NRT out, HND->LAX back — a real open-jaw shape, not a symmetric round trip.

    Neither Amadeus/Kiwi/SerpAPI's wired-up endpoints support an independent
    return-leg pair in one call, so route_optimizer runs it as two one-way
    fan-outs and tags results via NormalizedOffer.leg. This proves that
    end-to-end through the route, not just the pure _open_jaw_leg_requests unit.
    """
    body = {
        "origin": "SFO", "destination": "NRT", "departure_date": "2027-03-01",
        "return_date": "2027-03-10", "return_origin": "HND", "return_destination": "LAX",
        "include_nearby": False,
    }

    # Redis (unlike the DB) isn't rolled back between tests — clear any stale
    # entry so this test is deterministic regardless of run history.
    cache_key = _offers_cache_key(SearchRequest(**body))
    redis_client = redis_asyncio.from_url(get_settings().redis_url)
    await redis_client.delete(cache_key)

    async def amadeus_side_effect(req):
        if req.origin == "SFO":
            return [_fake_offer("amadeus", "SFO", "NRT", "900.00", "1",
                                datetime(2027, 3, 1, 8, 0))]
        return [_fake_offer("amadeus", "HND", "LAX", "650.00", "2",
                            datetime(2027, 3, 10, 8, 0))]

    mock_amadeus = AsyncMock(side_effect=amadeus_side_effect)
    mock_kiwi = AsyncMock(return_value=[])
    mock_serpapi = AsyncMock(return_value=[])
    try:
        with (
            patch("app.services.route_optimizer._search_amadeus", mock_amadeus),
            patch("app.services.route_optimizer._search_kiwi", mock_kiwi),
            patch("app.services.route_optimizer._search_serpapi", mock_serpapi),
        ):
            resp = await client.post("/api/v1/routes/search", json=body)

        assert resp.status_code == 200
        result = resp.json()
        assert result["offer_count"] == 2
        legs = {o["leg"] for o in result["offers"]}
        assert legs == {"outbound", "return"}
        outbound_offer = next(o for o in result["offers"] if o["leg"] == "outbound")
        return_offer = next(o for o in result["offers"] if o["leg"] == "return")
        assert outbound_offer["segments"][0]["origin"] == "SFO"
        assert return_offer["segments"][0]["origin"] == "HND"

        search = await db_session.get(Search, result["search_id"])
        assert search.return_origin == "HND"
        assert search.return_destination == "LAX"
    finally:
        await redis_client.delete(cache_key)
        await redis_client.aclose()


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
