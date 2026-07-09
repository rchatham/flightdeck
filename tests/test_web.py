"""Smoke tests for the dashboard route (no DB required)."""
from __future__ import annotations

import asyncio

import httpx

from app.main import app


def _get(path: str) -> httpx.Response:
    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    return asyncio.run(_run())


def test_dashboard_served_at_root():
    resp = _get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "FlightDeck" in resp.text
    # The page drives the real API endpoints — keep these paths in sync.
    for path in ("/api/v1/watches", "/api/v1/routes/search", "/api/v1/timing/analyze",
                 "/api/v1/timing/history", "/api/v1/deals/scan", "/api/v1/fares/hidden",
                 "/api/v1/points", "/api/v1/system/status"):
        assert path in resp.text


def test_dashboard_not_in_openapi_schema():
    resp = _get("/openapi.json")
    assert resp.status_code == 200
    assert "/" not in resp.json()["paths"]


def test_system_status_reports_watch_staleness():
    resp = _get("/api/v1/system/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "watches" in body
    assert "active_count" in body["watches"]
    assert "stalest_check_age_hours" in body["watches"]
    assert "stale" in body["watches"]
