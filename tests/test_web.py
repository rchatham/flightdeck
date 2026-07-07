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
    for path in ("/api/v1/watches", "/api/v1/routes/search", "/api/v1/timing/analyze"):
        assert path in resp.text


def test_dashboard_not_in_openapi_schema():
    resp = _get("/openapi.json")
    assert resp.status_code == 200
    assert "/" not in resp.json()["paths"]
