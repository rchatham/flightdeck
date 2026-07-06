"""SerpAPI Google Flights client.

SerpAPI scrapes Google Flights and returns structured JSON. Useful as a
sanity-check source — Google Flights pulls from a different fare cache than
Amadeus/Kiwi and sometimes surfaces deals the others miss.

Auth: simple `api_key` query param.
Endpoint: GET /search?engine=google_flights
Docs: https://serpapi.com/google-flights-api
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


class SerpApiError(Exception):
    """Raised for non-recoverable SerpAPI errors."""


_CABIN_TO_GOOGLE = {
    "economy": 1,
    "premium_economy": 2,
    "business": 3,
    "first": 4,
}


class SerpApiClient:
    BASE_URL = "https://serpapi.com"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or get_settings().serpapi_api_key
        self._client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "SerpApiClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def _get(self, params: dict[str, Any]) -> dict:
        if not self.api_key:
            raise SerpApiError(
                "SERPAPI_API_KEY not configured. Set it in .env to call SerpAPI."
            )
        params = {**params, "api_key": self.api_key}
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, max=4.0),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            reraise=True,
        ):
            with attempt:
                resp = await self._client.get("/search", params=params)
                resp.raise_for_status()
                return resp.json()
        raise SerpApiError("unreachable")  # pragma: no cover

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
        params: dict[str, Any] = {
            "engine": "google_flights",
            "departure_id": origin.upper(),
            "arrival_id": destination.upper(),
            "outbound_date": departure_date.isoformat(),
            "currency": "USD",
            "adults": adults,
            "travel_class": _CABIN_TO_GOOGLE.get(cabin_class, 1),
            "type": 2 if return_date is None else 1,  # 1=round-trip, 2=one-way
        }
        if return_date:
            params["return_date"] = return_date.isoformat()
        if non_stop:
            params["stops"] = 1  # Google Flights: 1 = nonstop only

        body = await self._get(params)

        # Google Flights returns `best_flights` (top picks) and `other_flights`.
        # Both arrays contain the same shape.
        all_results = (body.get("best_flights") or []) + (body.get("other_flights") or [])

        offers: list[NormalizedOffer] = []
        for raw in all_results[:max_results]:
            try:
                offers.append(_normalize_offer(raw))
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to normalize SerpAPI offer: %s", e)
        return offers


def _normalize_offer(raw: dict) -> NormalizedOffer:
    """Convert one SerpAPI Google-Flights `flights[i]` item into a NormalizedOffer.

    Each result has a `flights` array (one element per segment), `total_duration`
    in minutes, and a `price` in the requested currency.
    """
    price_usd = Decimal(str(raw.get("price", 0)))
    segments: list[Segment] = []
    flight_segments = raw.get("flights", [])
    stops = max(len(flight_segments) - 1, 0)

    for seg in flight_segments:
        dep = seg.get("departure_airport", {})
        arr = seg.get("arrival_airport", {})
        depart_at = datetime.fromisoformat(dep["time"]) if dep.get("time") else datetime.min
        arrive_at = datetime.fromisoformat(arr["time"]) if arr.get("time") else datetime.min
        duration = timedelta(minutes=int(seg.get("duration", 0)))
        # Google Flights flight number format: "DL 4561" — split on space
        flight_id = seg.get("flight_number", "").split()
        carrier = flight_id[0] if flight_id else ""
        flight_no = flight_id[1] if len(flight_id) > 1 else ""
        cabin_raw = (seg.get("travel_class") or "Economy").lower()
        cabin = "economy"
        if "business" in cabin_raw:
            cabin = "business"
        elif "first" in cabin_raw:
            cabin = "first"
        elif "premium" in cabin_raw:
            cabin = "premium_economy"
        segments.append(
            Segment(
                carrier=carrier,
                flight_no=flight_no,
                origin=dep.get("id", ""),
                destination=arr.get("id", ""),
                depart_at=depart_at,
                arrive_at=arrive_at,
                duration=duration,
                cabin=cabin,
            )
        )

    total_duration = timedelta(minutes=int(raw.get("total_duration", 0)))

    return NormalizedOffer(
        source="serpapi",
        source_id=raw.get("booking_token", ""),
        price_usd=price_usd,
        currency="USD",
        total_duration=total_duration,
        stops=stops,
        segments=segments,
        fare_type="regular",
        booking_url=None,  # Google Flights → user follows booking_token to retrieve
        deep_link=None,
        raw=raw,
    )
