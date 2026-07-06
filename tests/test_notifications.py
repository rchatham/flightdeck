"""Tests for alert notification delivery (ntfy + webhook channels)."""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from uuid import uuid4

import httpx

from app.config import Settings
from app.models import PriceAlert, PriceWatch
from app.services.notifications import notify_alert


def make_watch() -> PriceWatch:
    return PriceWatch(
        id=uuid4(),
        origin="SFO",
        destination="NRT",
        departure_date=date(2026, 10, 15),
        return_date=None,
        cabin_class="economy",
        target_price_usd=Decimal("800"),
    )


def make_alert(watch: PriceWatch) -> PriceAlert:
    return PriceAlert(
        id=uuid4(),
        watch_id=watch.id,
        kind="target_hit",
        price_usd=Decimal("750"),
        previous_price_usd=Decimal("900"),
        message="Price $750 is at or below your target $800 (101 days until departure).",
    )


def settings_with(**overrides) -> Settings:
    # _env_file=None keeps the developer's real .env out of unit tests.
    return Settings(_env_file=None, **overrides)


def run_notify(settings: Settings, transport: httpx.MockTransport) -> bool:
    watch = make_watch()
    alert = make_alert(watch)

    async def _run() -> bool:
        async with httpx.AsyncClient(transport=transport) as client:
            return await notify_alert(watch, alert, settings=settings, client=client)

    return asyncio.run(_run())


def test_no_channels_configured_returns_false():
    calls = []
    transport = httpx.MockTransport(lambda req: calls.append(req))
    assert run_notify(settings_with(), transport) is False
    assert calls == []


def test_ntfy_delivery_shape():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200)

    ok = run_notify(
        settings_with(ntfy_topic="test-topic"), httpx.MockTransport(handler)
    )
    assert ok is True
    assert len(seen) == 1
    req = seen[0]
    assert str(req.url) == "https://ntfy.sh/test-topic"
    assert "SFO->NRT" in req.headers["Title"]
    assert req.headers["Title"].isascii()  # HTTP headers reject UTF-8
    assert "target hit" in req.headers["Title"]
    assert req.headers["Priority"] == "4"
    assert b"target $800" in req.content


def test_webhook_delivery_payload():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200)

    ok = run_notify(
        settings_with(alert_webhook_url="https://example.test/hook"),
        httpx.MockTransport(handler),
    )
    assert ok is True
    import json

    body = json.loads(seen[0].content)
    assert body["route"] == "SFO-NRT"
    assert body["kind"] == "target_hit"
    assert body["price_usd"] == 750.0
    assert body["previous_price_usd"] == 900.0
    assert body["target_price_usd"] == 800.0
    assert body["departure_date"] == "2026-10-15"


def test_both_channels_fire():
    urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        urls.append(str(req.url))
        return httpx.Response(200)

    ok = run_notify(
        settings_with(ntfy_topic="t", alert_webhook_url="https://example.test/hook"),
        httpx.MockTransport(handler),
    )
    assert ok is True
    assert len(urls) == 2


def test_one_channel_failing_does_not_block_the_other():
    urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        urls.append(str(req.url))
        if "ntfy.sh" in str(req.url):
            return httpx.Response(500)
        return httpx.Response(200)

    ok = run_notify(
        settings_with(ntfy_topic="t", alert_webhook_url="https://example.test/hook"),
        httpx.MockTransport(handler),
    )
    assert ok is True  # webhook succeeded even though ntfy 500'd
    assert len(urls) == 2


def test_all_channels_failing_returns_false_without_raising():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    ok = run_notify(
        settings_with(ntfy_topic="t", alert_webhook_url="https://example.test/hook"),
        httpx.MockTransport(handler),
    )
    assert ok is False
