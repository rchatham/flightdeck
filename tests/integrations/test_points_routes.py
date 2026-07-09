"""Route-level tests for /api/v1/points — hits the real FastAPI app + DB session,
not just schemas or pure functions.
"""
from __future__ import annotations

from uuid import uuid4


async def test_list_programs_returns_seeded_rows(client):
    resp = await client.get("/api/v1/points")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert len(body["programs"]) == body["count"]

    program = body["programs"][0]
    assert "id" in program
    assert "program_name" in program
    assert "balance" in program
    assert isinstance(program["balance"], int)
    assert "transfer_partners" in program
    assert isinstance(program["transfer_partners"], list)
    assert "updated_at" in program


async def test_get_program_matches_list_entry(client):
    list_resp = await client.get("/api/v1/points")
    programs = list_resp.json()["programs"]
    assert programs
    target = programs[0]

    resp = await client.get(f"/api/v1/points/{target['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == target["id"]
    assert body["program_name"] == target["program_name"]
    assert body["balance"] == target["balance"]


async def test_get_unknown_program_404s(client):
    resp = await client.get(f"/api/v1/points/{uuid4()}")
    assert resp.status_code == 404


async def test_patch_updates_balance_and_roundtrips(client):
    list_resp = await client.get("/api/v1/points")
    programs = list_resp.json()["programs"]
    assert programs
    target = programs[0]
    new_balance = target["balance"] + 12345

    resp = await client.patch(
        f"/api/v1/points/{target['id']}", json={"balance": new_balance}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == target["id"]
    assert body["balance"] == new_balance

    get_resp = await client.get(f"/api/v1/points/{target['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["balance"] == new_balance


async def test_patch_allows_zero_balance(client):
    list_resp = await client.get("/api/v1/points")
    target = list_resp.json()["programs"][0]

    resp = await client.patch(f"/api/v1/points/{target['id']}", json={"balance": 0})
    assert resp.status_code == 200
    assert resp.json()["balance"] == 0


async def test_patch_unknown_program_404s(client):
    resp = await client.patch(f"/api/v1/points/{uuid4()}", json={"balance": 100})
    assert resp.status_code == 404


async def test_patch_negative_balance_422s(client):
    list_resp = await client.get("/api/v1/points")
    target = list_resp.json()["programs"][0]

    resp = await client.patch(f"/api/v1/points/{target['id']}", json={"balance": -1})
    assert resp.status_code == 422


async def test_estimate_redemptions_across_programs(client):
    resp = await client.post("/api/v1/points/estimate", json={"cash_price_usd": 500})
    assert resp.status_code == 200
    body = resp.json()
    assert float(body["cash_price_usd"]) == 500.0
    assert "estimates" in body
    assert isinstance(body["estimates"], list)

    list_resp = await client.get("/api/v1/points")
    program_count = list_resp.json()["count"]
    assert len(body["estimates"]) == program_count

    for est in body["estimates"]:
        assert "program_name" in est
        assert "cents_per_point" in est
        assert "points_needed" in est
        assert "balance" in est
        assert "sufficient" in est
        assert "shortfall" in est
        assert est["points_needed"] >= 0


async def test_estimate_zero_cash_price(client):
    resp = await client.post("/api/v1/points/estimate", json={"cash_price_usd": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert float(body["cash_price_usd"]) == 0.0


async def test_estimate_negative_cash_price_422s(client):
    resp = await client.post("/api/v1/points/estimate", json={"cash_price_usd": -50})
    assert resp.status_code == 422


async def test_estimate_missing_cash_price_422s(client):
    resp = await client.post("/api/v1/points/estimate", json={})
    assert resp.status_code == 422
