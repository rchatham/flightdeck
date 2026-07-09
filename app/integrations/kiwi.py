"""Kiwi Tequila API client.

Tequila is Kiwi's developer API. Useful for: multi-carrier itineraries that
the GDS-fed sources (Amadeus) miss, virtually-interlined / self-transfer
options, and hidden-city candidates (handled in Module 3).

Auth: simple `apikey` HTTP header — no OAuth dance.
Endpoint used: GET /v2/search
Docs: https://tequila.kiwi.com/portal/docs/tequila_api
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.integrations.types import NormalizedOffer, Segment

logger = logging.getLogger(__name__)


class KiwiError(Exception):
    """Raised for non-recoverable Kiwi API errors."""


_CABIN_TO_KIWI = {
    "economy": "M",
    "premium_economy": "W",
    "business": "C",
    "first": "F",
}


class KiwiClient:
    BASE_URL = "https://api.tequila.kiwi.com"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or get_settings().kiwi_api_key
        self._client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> KiwiClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict:
        if not self.api_key:
            raise KiwiError(
                "KIWI_API_KEY not configured. Set it in .env to call the Kiwi API."
            )
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.5, max=4.0),
                retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
                reraise=True,
            ):
                with attempt:
                    resp = await self._client.get(
                        path, params=params, headers={"apikey": self.api_key}
                    )
                    resp.raise_for_status()
                    return resp.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            raise KiwiError(f"Kiwi request failed: {e}") from e
        raise KiwiError("unreachable")  # pragma: no cover

    async def search_flight_offers(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None = None,
        adults: int = 1,
        cabin_class: str = "economy",
        max_results: int = 20,
        non_stop: bool = False,
        virtually_interlined: bool = False,
    ) -> list[NormalizedOffer]:
        """Search Tequila and return offers in the common NormalizedOffer shape.

        `virtually_interlined=True` enables Kiwi's self-transfer/hidden-city
        candidates — useful for Module 3 (hidden fares); skip for vanilla search.
        """
        # Tequila uses dd/mm/yyyy for date ranges. Single-day searches pass
        # date_from = date_to.
        date_str = departure_date.strftime("%d/%m/%Y")
        params: dict[str, Any] = {
            "fly_from": origin.upper(),
            "fly_to": destination.upper(),
            "date_from": date_str,
            "date_to": date_str,
            "adults": adults,
            "selected_cabins": _CABIN_TO_KIWI.get(cabin_class, "M"),
            "limit": max_results,
            "curr": "USD",
            "vehicle_type": "aircraft",
        }
        if return_date:
            r_str = return_date.strftime("%d/%m/%Y")
            params["return_from"] = r_str
            params["return_to"] = r_str
        if non_stop:
            params["max_stopovers"] = 0
        if not virtually_interlined:
            # Default: standard interline-ticketed only (no self-transfer)
            params["enable_vi"] = False

        body = await self._get("/v2/search", params)
        offers: list[NormalizedOffer] = []
        for raw in body.get("data", []):
            try:
                offers.append(_normalize_offer(raw))
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to normalize Kiwi offer %s: %s", raw.get("id"), e)
        return offers


def _normalize_offer(raw: dict) -> NormalizedOffer:
    """Convert one Tequila `data[]` item into a NormalizedOffer.

    Tequila offers contain a flat `route[]` of segments. `nightsInDest`
    indicates round-trip; we don't split outbound/inbound here.
    """
    price_usd = Decimal(str(raw.get("price", 0)))
    segments: list[Segment] = []
    stops = max(len(raw.get("route", [])) - 1, 0)
    total_duration_secs = 0

    for seg in raw.get("route", []):
        depart = datetime.fromisoformat(
            seg["local_departure"].replace("Z", "+00:00")
        ).replace(tzinfo=None)
        arrive = datetime.fromisoformat(
            seg["local_arrival"].replace("Z", "+00:00")
        ).replace(tzinfo=None)
        seg_duration = arrive - depart
        total_duration_secs += int(seg_duration.total_seconds())
        segments.append(
            Segment(
                carrier=seg.get("airline", ""),
                flight_no=str(seg.get("flight_no", "")),
                origin=seg.get("flyFrom", ""),
                destination=seg.get("flyTo", ""),
                depart_at=depart,
                arrive_at=arrive,
                duration=seg_duration,
                cabin="economy",  # Tequila doesn't return per-segment cabin in basic /search
            )
        )

    fare_type = "regular"
    if raw.get("virtual_interlining"):
        fare_type = "self_transfer"

    return NormalizedOffer(
        source="kiwi",
        source_id=raw.get("id", ""),
        price_usd=price_usd,
        currency="USD",
        total_duration=timedelta(seconds=total_duration_secs),
        stops=stops,
        segments=segments,
        fare_type=fare_type,
        booking_url=raw.get("deep_link"),
        deep_link=raw.get("deep_link"),
        raw=raw,
    )
