"""Route-level tests for /api/v1/system — hits the real FastAPI app + DB session,
not just schemas or pure functions.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import update

from app.models import PriceWatch


async def test_system_status_reports_infra_and_shape(client):
    resp = await client.get("/api/v1/system/status")
    assert resp.status_code == 200
    body = resp.json()

    assert body["postgres"]["status"] == "ok"
    assert body["redis"]["status"] == "ok"

    assert "amadeus" in body["fare_sources"]
    assert "kiwi" in body["fare_sources"]
    assert "serpapi" in body["fare_sources"]

    assert "ntfy" in body["notifications"]
    assert "webhook" in body["notifications"]

    assert "active_count" in body["watches"]
    assert "stalest_check_age_hours" in body["watches"]
    assert "stale" in body["watches"]


async def test_system_status_stale_watch_marks_stale(client, db_session):
    # Deactivate any pre-existing active watches (dev DB, not a clean fixture)
    # so the age assertion below reflects this test's watch specifically.
    await db_session.execute(update(PriceWatch).values(active=False))

    watch = PriceWatch(
        origin="SFO",
        destination="NRT",
        departure_date=date(2027, 3, 1),
        cabin_class="economy",
        active=True,
        last_checked_at=datetime.now(UTC) - timedelta(hours=10),
    )
    db_session.add(watch)
    await db_session.commit()

    resp = await client.get("/api/v1/system/status")
    assert resp.status_code == 200
    body = resp.json()

    assert body["watches"]["active_count"] >= 1
    assert body["watches"]["stale"] is True
    assert body["watches"]["stalest_check_age_hours"] > 7


async def test_system_status_never_checked_watch_not_stale(client, db_session):
    # Deactivate any pre-existing active watches (dev DB, not a clean fixture)
    # so this test's own null-last_checked_at watch is the only one that can
    # influence staleness — proving a null timestamp alone never makes it stale.
    await db_session.execute(update(PriceWatch).values(active=False))

    watch = PriceWatch(
        origin="LAX",
        destination="HND",
        departure_date=date(2027, 4, 1),
        cabin_class="economy",
        active=True,
        last_checked_at=None,
    )
    db_session.add(watch)
    await db_session.commit()

    resp = await client.get("/api/v1/system/status")
    assert resp.status_code == 200
    body = resp.json()

    assert body["watches"]["active_count"] >= 1
    assert body["watches"]["stale"] is False
    assert body["watches"]["stalest_check_age_hours"] is None
