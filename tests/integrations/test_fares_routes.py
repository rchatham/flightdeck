"""Route-level tests for /api/v1/fares — hits the real FastAPI app.

The /hidden route has no DB dependency; it fans out to live provider searches
via discover_opportunities. With no provider API keys configured in this dev
environment, it legitimately returns zero opportunities — these tests assert
the response envelope is well-formed rather than asserting specific fares.
"""
from __future__ import annotations


def _body(**overrides) -> dict:
    payload = {
        "origin": "sfo",
        "destination": "nrt",
        "departure_date": "2027-03-01",
        "return_date": "2027-03-10",
        "passengers": 1,
        "strategies": ["hidden_city", "split_ticket"],
        "has_checked_bag": False,
        **overrides,
    }
    return payload


async def test_hidden_fares_happy_path(client):
    resp = await client.post("/api/v1/fares/hidden", json=_body())
    assert resp.status_code == 200
    body = resp.json()

    assert body["origin"] == "SFO"
    assert body["destination"] == "NRT"
    assert body["departure_date"] == "2027-03-01"
    assert body["return_date"] == "2027-03-10"
    assert "opportunity_count" in body
    assert isinstance(body["opportunities"], list)
    assert body["opportunity_count"] == len(body["opportunities"])


async def test_hidden_fares_one_way_no_return_date(client):
    body = _body()
    body.pop("return_date")
    resp = await client.post("/api/v1/fares/hidden", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["return_date"] is None
    assert isinstance(data["opportunities"], list)


async def test_hidden_fares_default_strategies_when_omitted(client):
    body = _body()
    body.pop("strategies")
    resp = await client.post("/api/v1/fares/hidden", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["opportunities"], list)


async def test_hidden_fares_multi_city_strategy(client):
    resp = await client.post(
        "/api/v1/fares/hidden", json=_body(strategies=["multi_city"])
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["opportunities"], list)


async def test_hidden_fares_invalid_strategy_returns_400(client):
    resp = await client.post(
        "/api/v1/fares/hidden", json=_body(strategies=["not_a_real_strategy"])
    )
    assert resp.status_code == 400
    assert "Unknown strategy" in resp.json()["detail"]


async def test_hidden_fares_rejects_bad_origin_length(client):
    resp = await client.post("/api/v1/fares/hidden", json=_body(origin="SF"))
    assert resp.status_code == 422


async def test_hidden_fares_rejects_too_many_passengers(client):
    resp = await client.post("/api/v1/fares/hidden", json=_body(passengers=10))
    assert resp.status_code == 422


async def test_hidden_fares_rejects_missing_required_field(client):
    body = _body()
    body.pop("origin")
    resp = await client.post("/api/v1/fares/hidden", json=body)
    assert resp.status_code == 422
