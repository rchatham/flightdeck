"""Route-level tests for /api/v1 airports/resolve and deals/scan — hits the
real FastAPI app + DB session, not just schemas or pure functions.

Fare sources (Amadeus/Kiwi/SerpAPI) have no API keys configured in this dev
environment, so `/deals/scan` legitimately returns zero offers/opportunities.
That's expected — these tests only assert the response envelope is
well-formed, not that any deals were actually found.
"""
from __future__ import annotations


async def test_resolve_airport_by_iata_code(client):
    resp = await client.get("/api/v1/airports/resolve", params={"q": "SFO"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "SFO"
    assert body["kind"] == "iata"
    assert body["airports"]
    assert body["airports"][0]["iata_code"] == "SFO"


async def test_resolve_airport_by_city_name(client):
    resp = await client.get("/api/v1/airports/resolve", params={"q": "tokyo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "name"
    assert body["airports"]
    assert any("tokyo" in a["city"].lower() for a in body["airports"])


async def test_resolve_airport_respects_limit(client):
    resp = await client.get(
        "/api/v1/airports/resolve", params={"q": "SFO", "limit": 2}
    )
    assert resp.status_code == 200
    assert len(resp.json()["airports"]) <= 2


async def test_resolve_unresolvable_query_returns_empty_airports(client):
    # Not a lat/lon, not a known 3-letter code, no name match, and not even
    # shaped like an IATA code — resolve_location() falls through to an
    # empty-airports "name" result rather than raising.
    resp = await client.get("/api/v1/airports/resolve", params={"q": "zzznotreal"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["airports"] == []


async def test_resolve_missing_query_param_422s(client):
    resp = await client.get("/api/v1/airports/resolve")
    assert resp.status_code == 422


async def test_deals_scan_happy_path_well_formed_envelope(client):
    resp = await client.post(
        "/api/v1/deals/scan",
        json={
            "origin": "SFO",
            "destination": "NRT",
            "date_from": "2027-03-01",
            "date_to": "2027-03-03",
            "max_searches": 4,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["origin_airports"]
    assert body["destination_airports"]
    assert body["date_from"] == "2027-03-01"
    assert body["date_to"] == "2027-03-03"
    assert body["searches_run"] >= 1
    assert body["dates_sampled"] >= 1
    assert "by_date" in body
    assert "opportunities" in body
    assert isinstance(body["by_date"], list)
    assert isinstance(body["opportunities"], list)


async def test_deals_scan_with_trip_length_and_hacker_fares(client):
    resp = await client.post(
        "/api/v1/deals/scan",
        json={
            "origin": "SFO",
            "destination": "NRT",
            "date_from": "2027-04-01",
            "date_to": "2027-04-02",
            "trip_length_days": 7,
            "max_searches": 5,
            "include_hacker_fares": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["searches_run"] >= 1
    assert "opportunities" in body


async def test_deals_scan_unresolvable_origin_404s(client):
    resp = await client.post(
        "/api/v1/deals/scan",
        json={
            "origin": "zzznotreal",
            "destination": "NRT",
            "date_from": "2027-03-01",
            "date_to": "2027-03-02",
            "max_searches": 4,
        },
    )
    assert resp.status_code == 404


async def test_deals_scan_backwards_date_range_422s(client):
    resp = await client.post(
        "/api/v1/deals/scan",
        json={
            "origin": "SFO",
            "destination": "NRT",
            "date_from": "2027-03-05",
            "date_to": "2027-03-01",
            "max_searches": 4,
        },
    )
    assert resp.status_code == 422


async def test_deals_scan_missing_required_fields_422s(client):
    resp = await client.post("/api/v1/deals/scan", json={"origin": "SFO"})
    assert resp.status_code == 422
