"""Watch checking — fan out a search for a watched trip, record the price,
run the Hook 4 alert rule, and persist any alert.

Used by both the Celery watch checker (scheduled) and the API's force-check
endpoint (interactive), so all state transitions live here in one place.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.search import SearchRequest
from app.models import PriceAlert, PriceHistory, PriceWatch
from app.services.alert_rules import (
    AlertDecision,
    PriceObservation,
    WatchSnapshot,
    evaluate_watch,
)
from app.services.notifications import notify_alert
from app.services.route_optimizer import _fan_out_sources

logger = logging.getLogger(__name__)


@dataclass
class CheckOutcome:
    watch_id: str
    offers_found: int
    cheapest_price_usd: Decimal | None
    alert: PriceAlert | None
    deactivated: bool = False  # watch expired (departure date passed)


def _route_key(watch: PriceWatch) -> str:
    return f"{watch.origin}-{watch.destination}:{watch.departure_date.isoformat()}"


def _snapshot(watch: PriceWatch) -> WatchSnapshot:
    return WatchSnapshot(
        target_price_usd=watch.target_price_usd,
        last_price_usd=watch.last_price_usd,
        lowest_seen_usd=watch.lowest_seen_usd,
        last_alerted_price_usd=watch.last_alerted_price_usd,
        last_alerted_at=watch.last_alerted_at,
        days_until_departure=(watch.departure_date - date.today()).days,
    )


async def check_watch(session: AsyncSession, watch: PriceWatch) -> CheckOutcome:
    """Run one check cycle for a watch. Commits its own state changes."""
    now = datetime.now(UTC)

    # Expired watches deactivate instead of burning API quota forever.
    if watch.departure_date < date.today():
        watch.active = False
        await session.commit()
        return CheckOutcome(str(watch.id), 0, None, None, deactivated=True)

    req = SearchRequest(
        origin=watch.origin,
        destination=watch.destination,
        departure_date=watch.departure_date,
        return_date=watch.return_date,
        passengers=1,
        cabin_class=watch.cabin_class,
        include_nearby=False,
    )
    offers = await _fan_out_sources(req)
    watch.last_checked_at = now

    if not offers:
        await session.commit()
        return CheckOutcome(str(watch.id), 0, None, None)

    cheapest = min(offers, key=lambda o: o.price_usd)
    price = cheapest.price_usd

    # Every watch check doubles as a price-history observation, feeding the
    # Hook 2 timing analyzer.
    session.add(PriceHistory(
        route_key=_route_key(watch),
        price_usd=price,
        source=cheapest.source,
        cabin_class=watch.cabin_class,
        days_until_departure=(watch.departure_date - date.today()).days,
    ))

    # Evaluate the alert rule against pre-update state, then roll state forward.
    decision: AlertDecision = evaluate_watch(
        PriceObservation(price_usd=price, source=cheapest.source, observed_at=now),
        _snapshot(watch),
    )

    previous_price = watch.last_price_usd
    watch.last_price_usd = price
    if watch.lowest_seen_usd is None or price < watch.lowest_seen_usd:
        watch.lowest_seen_usd = price

    alert: PriceAlert | None = None
    if decision.fire and decision.kind is not None:
        alert = PriceAlert(
            watch_id=watch.id,
            kind=decision.kind.value,
            price_usd=price,
            previous_price_usd=previous_price,
            message=decision.message,
        )
        session.add(alert)
        watch.last_alerted_at = now
        watch.last_alerted_price_usd = price
        logger.info("alert fired for watch %s: %s at $%s", watch.id, decision.kind.value, price)

    await session.commit()

    # Push AFTER commit — the alert is durable even if delivery fails, and
    # notify_alert never raises.
    if alert is not None:
        await notify_alert(watch, alert)

    return CheckOutcome(str(watch.id), len(offers), price, alert)
