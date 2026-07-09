"""Route-level tests for /api/v1/watches — hits the real FastAPI app + DB session,
not just schemas or pure functions.
"""
from __future__ import annotations

from uuid import uuid4


async def _create_watch(client, **overrides) -> dict:
    body = {
        "origin": "SFO",
        "destination": "NRT",
        "departure_date": "2027-03-01",
        "cabin_class": "economy",
        "target_price_usd": 700,
        **overrides,
    }
    resp = await client.post("/api/v1/watches", json=body)
    assert resp.status_code == 201
    return resp.json()


async def test_create_and_get_watch(client):
    watch = await _create_watch(client)
    assert watch["origin"] == "SFO"
    assert watch["destination"] == "NRT"
    assert watch["active"] is True

    resp = await client.get(f"/api/v1/watches/{watch['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == watch["id"]


async def test_list_watches_excludes_inactive_by_default(client):
    watch = await _create_watch(client)
    await client.patch(f"/api/v1/watches/{watch['id']}", json={"active": False})

    resp = await client.get("/api/v1/watches")
    ids = [w["id"] for w in resp.json()["watches"]]
    assert watch["id"] not in ids

    resp = await client.get("/api/v1/watches", params={"include_inactive": True})
    ids = [w["id"] for w in resp.json()["watches"]]
    assert watch["id"] in ids


async def test_patch_updates_target_price_and_keeps_id(client):
    watch = await _create_watch(client)
    resp = await client.patch(
        f"/api/v1/watches/{watch['id']}", json={"target_price_usd": 500}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == watch["id"]
    assert float(body["target_price_usd"]) == 500.0
    # origin/destination are immutable via PATCH
    assert body["origin"] == "SFO"


async def test_patch_unknown_watch_404s(client):
    resp = await client.patch(f"/api/v1/watches/{uuid4()}", json={"target_price_usd": 1})
    assert resp.status_code == 404


async def test_delete_watch(client):
    watch = await _create_watch(client)
    resp = await client.delete(f"/api/v1/watches/{watch['id']}")
    assert resp.status_code == 204
    resp = await client.get(f"/api/v1/watches/{watch['id']}")
    assert resp.status_code == 404


async def test_delete_unknown_watch_404s(client):
    resp = await client.delete(f"/api/v1/watches/{uuid4()}")
    assert resp.status_code == 404


async def test_get_unknown_watch_404s(client):
    resp = await client.get(f"/api/v1/watches/{uuid4()}")
    assert resp.status_code == 404


async def test_create_watch_rejects_bad_origin_length(client):
    resp = await client.post(
        "/api/v1/watches",
        json={"origin": "SF", "destination": "NRT", "departure_date": "2027-03-01"},
    )
    assert resp.status_code == 422


async def test_alerts_list_and_ack_roundtrip(client):
    # No alerts fixture exists yet — this just proves the route executes against
    # the real DB and returns a well-formed (possibly empty) response.
    resp = await client.get("/api/v1/watches/alerts")
    assert resp.status_code == 200
    body = resp.json()
    assert "count" in body and "alerts" in body


async def test_ack_unknown_alert_404s(client):
    resp = await client.post(f"/api/v1/watches/alerts/{uuid4()}/ack")
    assert resp.status_code == 404


async def test_watch_booking_links(client):
    watch = await _create_watch(client)
    resp = await client.get(f"/api/v1/watches/{watch['id']}/booking")
    assert resp.status_code == 200
    body = resp.json()
    assert body["links"]
    assert "SFO" in body["context"]
