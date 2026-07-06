"""Alert notification delivery.

Pushes fired alerts to whichever channels are configured in settings:
  • ntfy  — https://ntfy.sh pub/sub push; subscribe to your topic on any
    device. Configure FLIGHTDECK_NTFY_TOPIC (pick something unguessable —
    topics are effectively passwords).
  • webhook — POST a JSON payload to FLIGHTDECK_ALERT_WEBHOOK_URL for
    anything custom (Slack bridge, home automation, etc.).

Delivery is best-effort: failures are logged, never raised, and never
block the watch-check cycle. Alerts always land in the DB regardless.
"""
from __future__ import annotations

import logging

import httpx

from app.config import Settings, get_settings
from app.models import PriceAlert, PriceWatch
from app.services.alert_rules import AlertKind

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0

# ntfy priority: 5=max/urgent, 4=high, 3=default, 2=low, 1=min.
_NTFY_PRIORITY = {
    AlertKind.TARGET_HIT.value: "4",
    AlertKind.NEW_LOW.value: "4",
    AlertKind.PRICE_DROP.value: "3",
    AlertKind.PRICE_SPIKE.value: "5",  # rising fare = act now or pay more
}

_NTFY_TAGS = {
    AlertKind.TARGET_HIT.value: "dart,airplane",
    AlertKind.NEW_LOW.value: "chart_with_downwards_trend,airplane",
    AlertKind.PRICE_DROP.value: "chart_with_downwards_trend,airplane",
    AlertKind.PRICE_SPIKE.value: "chart_with_upwards_trend,warning",
}


def _title(watch: PriceWatch, alert: PriceAlert) -> str:
    # ASCII only — this goes in an HTTP header, which rejects UTF-8.
    kind = alert.kind.replace("_", " ")
    return (
        f"{watch.origin}->{watch.destination} ${float(alert.price_usd):,.0f} ({kind})"
    )


def _payload(watch: PriceWatch, alert: PriceAlert) -> dict:
    return {
        "alert_id": str(alert.id),
        "watch_id": str(watch.id),
        "kind": alert.kind,
        "route": f"{watch.origin}-{watch.destination}",
        "departure_date": watch.departure_date.isoformat(),
        "return_date": watch.return_date.isoformat() if watch.return_date else None,
        "cabin_class": watch.cabin_class,
        "price_usd": float(alert.price_usd),
        "previous_price_usd": (
            float(alert.previous_price_usd)
            if alert.previous_price_usd is not None else None
        ),
        "target_price_usd": (
            float(watch.target_price_usd)
            if watch.target_price_usd is not None else None
        ),
        "message": alert.message,
    }


async def _send_ntfy(
    client: httpx.AsyncClient, settings: Settings, watch: PriceWatch, alert: PriceAlert
) -> bool:
    url = f"{settings.ntfy_server.rstrip('/')}/{settings.ntfy_topic}"
    resp = await client.post(
        url,
        content=alert.message.encode(),
        headers={
            "Title": _title(watch, alert),
            "Priority": _NTFY_PRIORITY.get(alert.kind, "3"),
            "Tags": _NTFY_TAGS.get(alert.kind, "airplane"),
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return True


async def _send_webhook(
    client: httpx.AsyncClient, settings: Settings, watch: PriceWatch, alert: PriceAlert
) -> bool:
    resp = await client.post(
        settings.alert_webhook_url, json=_payload(watch, alert), timeout=_TIMEOUT
    )
    resp.raise_for_status()
    return True


async def notify_alert(
    watch: PriceWatch,
    alert: PriceAlert,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Deliver an alert to all configured channels. Returns True if any succeeded.

    `settings`/`client` are injectable for tests; production callers pass neither.
    """
    settings = settings or get_settings()
    channels = []
    if settings.ntfy_topic:
        channels.append(("ntfy", _send_ntfy))
    if settings.alert_webhook_url:
        channels.append(("webhook", _send_webhook))
    if not channels:
        return False

    owns_client = client is None
    client = client or httpx.AsyncClient()
    delivered = False
    try:
        for name, send in channels:
            try:
                delivered = await send(client, settings, watch, alert) or delivered
            except Exception as e:  # noqa: BLE001 — delivery must never break checks
                logger.warning("alert notification via %s failed: %s", name, e)
    finally:
        if owns_client:
            await client.aclose()
    return delivered
