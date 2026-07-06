"""Amadeus Self-Service API client.

Auth: OAuth2 client-credentials. Token TTL is ~30 min; we cache it in-memory and
refresh on demand. For a single-user MVP that's plenty — switch to Redis if we
ever run multiple processes.

Endpoint used: GET /v2/shopping/flight-offers
Docs: https://developers.amadeus.com/self-service/category/flights
"""
from __future__ import annotations

import logging
import time
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


class AmadeusError(Exception):
    """Raised for non-recoverable Amadeus API errors."""


# Cabin class mapping (FlightDeck → Amadeus travelClass param)
_CABIN_TO_AMADEUS = {
    "economy": "ECONOMY",
    "premium_economy": "PREMIUM_ECONOMY",
    "business": "BUSINESS",
    "first": "FIRST",
}


class AmadeusClient:
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        s = get_settings()
        self.api_key = api_key or s.amadeus_api_key
        self.api_secret = api_secret or s.amadeus_api_secret
        self.base_url = (base_url or s.amadeus_base_url).rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
        self._token: str | None = None
        self._token_expires_at: float = 0.0  # epoch seconds

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AmadeusClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    # --- Auth -----------------------------------------------------------------

    async def _ensure_token(self) -> str:
        if not self.api_key or not self.api_secret:
            raise AmadeusError(
                "AMADEUS_API_KEY / AMADEUS_API_SECRET not configured. "
                "Set them in .env to call the Amadeus API."
            )
        # Refresh 30s before expiry to avoid races
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        resp = await self._client.post(
            "/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.api_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise AmadeusError(f"Amadeus auth failed: {resp.status_code} {resp.text}")
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = time.time() + body.get("expires_in", 1800)
        logger.debug("Amadeus token acquired (expires in %ss)", body.get("expires_in"))
        return self._token

    async def _authed_get(self, path: str, params: dict[str, Any]) -> dict:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, max=4.0),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            reraise=True,
        ):
            with attempt:
                token = await self._ensure_token()
                resp = await self._client.get(
                    path,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
                # 401 → token rotated/revoked, force refresh on next attempt
                if resp.status_code == 401:
                    self._token = None
                    self._token_expires_at = 0.0
                resp.raise_for_status()
                return resp.json()
        raise AmadeusError("unreachable")  # pragma: no cover

    # --- Search ---------------------------------------------------------------

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
    ) -> list[NormalizedOffer]:
        """Search flight offers and return them in the common NormalizedOffer shape."""
        params: dict[str, Any] = {
            "originLocationCode": origin.upper(),
            "destinationLocationCode": destination.upper(),
            "departureDate": departure_date.isoformat(),
            "adults": adults,
            "max": max_results,
            "currencyCode": "USD",
            "travelClass": _CABIN_TO_AMADEUS.get(cabin_class, "ECONOMY"),
        }
        if return_date:
            params["returnDate"] = return_date.isoformat()
        if non_stop:
            params["nonStop"] = "true"

        body = await self._authed_get("/v2/shopping/flight-offers", params)
        offers = []
        for raw in body.get("data", []):
            try:
                offers.append(_normalize_offer(raw))
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to normalize Amadeus offer %s: %s", raw.get("id"), e)
        return offers


# --- Normalization ------------------------------------------------------------


def _parse_iso8601_duration(s: str) -> timedelta:
    """Parse an ISO-8601 duration like 'PT12H35M' into a timedelta.

    Amadeus emits PnDTnHnMnS. We only ever see hours and minutes in flight
    durations, but handle days defensively.
    """
    if not s.startswith("P"):
        raise ValueError(f"not an ISO-8601 duration: {s!r}")
    body = s[1:]
    days = hours = minutes = seconds = 0
    if "T" in body:
        date_part, time_part = body.split("T", 1)
    else:
        date_part, time_part = body, ""
    if date_part.endswith("D"):
        days = int(date_part[:-1])

    num = ""
    for ch in time_part:
        if ch.isdigit():
            num += ch
        elif ch == "H":
            hours = int(num); num = ""
        elif ch == "M":
            minutes = int(num); num = ""
        elif ch == "S":
            seconds = int(num); num = ""
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def _normalize_offer(raw: dict) -> NormalizedOffer:
    """Convert one Amadeus flight-offer object into a NormalizedOffer."""
    price_section = raw.get("price", {})
    grand_total = price_section.get("grandTotal") or price_section.get("total")
    currency = price_section.get("currency", "USD")
    price_usd = Decimal(grand_total) if grand_total else Decimal("0")

    segments: list[Segment] = []
    total_duration = timedelta()
    stops = 0

    # Amadeus offers contain `itineraries`, each with `segments`
    for itinerary in raw.get("itineraries", []):
        itin_duration = itinerary.get("duration")
        if itin_duration:
            total_duration += _parse_iso8601_duration(itin_duration)
        for seg_raw in itinerary.get("segments", []):
            dep = seg_raw["departure"]
            arr = seg_raw["arrival"]
            cabin = "economy"
            for tp in raw.get("travelerPricings", []):
                for fd in tp.get("fareDetailsBySegment", []):
                    if fd.get("segmentId") == seg_raw.get("id"):
                        cabin = (fd.get("cabin") or "ECONOMY").lower()
                        break
            segments.append(
                Segment(
                    carrier=seg_raw["carrierCode"],
                    flight_no=str(seg_raw.get("number", "")),
                    origin=dep["iataCode"],
                    destination=arr["iataCode"],
                    depart_at=datetime.fromisoformat(dep["at"]),
                    arrive_at=datetime.fromisoformat(arr["at"]),
                    duration=_parse_iso8601_duration(seg_raw["duration"]),
                    cabin=cabin,
                )
            )
        # stops in this itinerary = number of segments - 1
        seg_count = len(itinerary.get("segments", []))
        stops += max(seg_count - 1, 0)

    return NormalizedOffer(
        source="amadeus",
        source_id=raw.get("id", ""),
        price_usd=price_usd,
        currency=currency,
        total_duration=total_duration,
        stops=stops,
        segments=segments,
        fare_type="regular",
        booking_url=None,
        deep_link=None,
        raw=raw,
    )
