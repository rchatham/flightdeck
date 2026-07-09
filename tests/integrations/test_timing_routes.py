"""Route-level tests for /api/v1/timing — hits the real FastAPI app + DB session,
not just schemas or pure functions.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import PriceHistory


async def test_analyze_no_history_returns_well_formed_recommendation(client):
    resp = await client.get(
        "/api/v1/timing/analyze",
        params={
            "origin": "ZZZ",
            "destination": "YYY",
            "departure_date": "2027-06-15",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["route"] == "ZZZ-YYY"
    assert body["departure_date"] == "2027-06-15"
    assert body["sample_count"] == 0
    assert body["median_price"] is None
    assert body["verdict"]
    assert isinstance(body["confidence"], float)
    assert body["reasoning"]


async def test_analyze_uppercases_origin_and_destination(client):
    resp = await client.get(
        "/api/v1/timing/analyze",
        params={
            "origin": "zzz",
            "destination": "yyy",
            "departure_date": "2027-06-15",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["route"] == "ZZZ-YYY"


async def test_analyze_rejects_bad_origin_length(client):
    resp = await client.get(
        "/api/v1/timing/analyze",
        params={
            "origin": "ZZ",
            "destination": "YYY",
            "departure_date": "2027-06-15",
        },
    )
    assert resp.status_code == 422


async def test_analyze_rejects_missing_departure_date(client):
    resp = await client.get(
        "/api/v1/timing/analyze",
        params={"origin": "ZZZ", "destination": "YYY"},
    )
    assert resp.status_code == 422


async def test_analyze_rejects_out_of_range_lookback_days(client):
    resp = await client.get(
        "/api/v1/timing/analyze",
        params={
            "origin": "ZZZ",
            "destination": "YYY",
            "departure_date": "2027-06-15",
            "lookback_days": 1,
        },
    )
    assert resp.status_code == 422


async def test_history_no_matching_rows_returns_empty(client):
    resp = await client.get("/api/v1/timing/history", params={"route_key": "ZZZ-YYY"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["route_key"] == "ZZZ-YYY"
    assert body["point_count"] == 0
    assert body["points"] == []


async def test_history_rejects_missing_route_key(client):
    resp = await client.get("/api/v1/timing/history")
    assert resp.status_code == 422


async def test_history_returns_inserted_price_points(client, db_session):
    route_key = "AAA-BBB"
    now = datetime.now(UTC)
    db_session.add_all(
        [
            PriceHistory(
                route_key=route_key,
                price_usd=Decimal("450.00"),
                source="test-fixture",
                cabin_class="economy",
                days_until_departure=45,
                recorded_at=now - timedelta(days=2),
            ),
            PriceHistory(
                route_key=route_key,
                price_usd=Decimal("410.00"),
                source="test-fixture",
                cabin_class="economy",
                days_until_departure=44,
                recorded_at=now - timedelta(days=1),
            ),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/timing/history", params={"route_key": route_key})
    assert resp.status_code == 200
    body = resp.json()
    assert body["route_key"] == route_key
    assert body["point_count"] == 2
    prices = {p["price_usd"] for p in body["points"]}
    assert prices == {"450.00", "410.00"}
    # oldest first
    assert body["points"][0]["price_usd"] == "450.00"
    assert body["points"][1]["price_usd"] == "410.00"


async def test_analyze_reads_through_db_for_seeded_route(client, db_session):
    route_key = "CCC-DDD:2027-09-01"
    now = datetime.now(UTC)
    for i in range(10):
        db_session.add(
            PriceHistory(
                route_key=route_key,
                price_usd=Decimal("500.00"),
                source="test-fixture",
                cabin_class="economy",
                days_until_departure=60 - i,
                recorded_at=now - timedelta(days=10 - i),
            )
        )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/timing/analyze",
        params={
            "origin": "CCC",
            "destination": "DDD",
            "departure_date": "2027-09-01",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sample_count"] == 10
    assert Decimal(body["median_price"]) == Decimal("500.00")
