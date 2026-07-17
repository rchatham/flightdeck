"""Route optimizer service.

Steps 4–6: multi-source fan-out (Amadeus + Kiwi + SerpAPI), dedup across sources,
rank via the `score_offer` hook, persist Search + FlightOffer rows.

Public entrypoint: `run_search(session, request)` — accepts a SearchRequest schema,
returns the persisted Search ID + ranked list of FlightOffer rows.

Each source is called in parallel via asyncio.gather. A failing source logs a
warning and is skipped — never blocks the response. A per-provider semaphore
caps concurrency so a wide fan-out (e.g. a deal scan across many dates) can't
hammer a single provider, and a short-TTL Redis cache collapses duplicate
identical searches (e.g. repeated watch checks) into one provider round-trip.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.search import SearchRequest
from app.integrations.amadeus import AmadeusClient, AmadeusError
from app.integrations.kiwi import KiwiClient, KiwiError
from app.integrations.serpapi import SerpApiClient, SerpApiError
from app.integrations.types import NormalizedOffer, Segment
from app.models import FlightOffer, Search
from app.services.cache import get_or_set
from app.services.dedup import dedupe_offers
from app.services.geo import expand_airport
from app.services.ranking import RankingPreferences, score_offer

logger = logging.getLogger(__name__)

# Cap concurrent in-flight requests per provider so a wide fan-out (many
# dates/airports in a deal scan) can't hammer any one of them at once.
_PROVIDER_CONCURRENCY = 4
_amadeus_sem = asyncio.Semaphore(_PROVIDER_CONCURRENCY)
_kiwi_sem = asyncio.Semaphore(_PROVIDER_CONCURRENCY)
_serpapi_sem = asyncio.Semaphore(_PROVIDER_CONCURRENCY)

# Offer lists change fast; this only exists to collapse duplicate/rapid-fire
# identical searches (repeated watch checks, a deal scan re-hitting the same
# date), not to serve stale prices.
_OFFERS_CACHE_TTL_SECONDS = 300


async def _search_amadeus(req: SearchRequest) -> list[NormalizedOffer]:
    async with _amadeus_sem, AmadeusClient() as client:
        try:
            return await client.search_flight_offers(
                origin=req.origin,
                destination=req.destination,
                departure_date=req.departure_date,
                return_date=req.return_date,
                adults=req.passengers,
                cabin_class=req.cabin_class,
                non_stop=(req.max_stops == 0),
            )
        except AmadeusError as e:
            logger.warning("Amadeus search failed: %s", e)
            return []
        except Exception as e:  # noqa: BLE001
            logger.exception("Amadeus search crashed: %s", e)
            return []


async def _search_kiwi(req: SearchRequest) -> list[NormalizedOffer]:
    async with _kiwi_sem, KiwiClient() as client:
        try:
            return await client.search_flight_offers(
                origin=req.origin,
                destination=req.destination,
                departure_date=req.departure_date,
                return_date=req.return_date,
                adults=req.passengers,
                cabin_class=req.cabin_class,
                non_stop=(req.max_stops == 0),
                virtually_interlined=False,
            )
        except KiwiError as e:
            logger.warning("Kiwi search failed: %s", e)
            return []
        except Exception as e:  # noqa: BLE001
            logger.exception("Kiwi search crashed: %s", e)
            return []


async def _search_serpapi(req: SearchRequest) -> list[NormalizedOffer]:
    async with _serpapi_sem, SerpApiClient() as client:
        try:
            return await client.search_flight_offers(
                origin=req.origin,
                destination=req.destination,
                departure_date=req.departure_date,
                return_date=req.return_date,
                adults=req.passengers,
                cabin_class=req.cabin_class,
                non_stop=(req.max_stops == 0),
            )
        except SerpApiError as e:
            logger.warning("SerpAPI search failed: %s", e)
            return []
        except Exception as e:  # noqa: BLE001
            logger.exception("SerpAPI search crashed: %s", e)
            return []


def _offers_cache_key(req: SearchRequest) -> str:
    """Deterministic cache key for a single (origin, destination) search.

    Only the fields that affect provider results are hashed — anything else
    on SearchRequest (e.g. include_nearby, flex_days) is handled by the
    caller expanding into per-pair requests before this is called.
    """
    payload = {
        "origin": req.origin,
        "destination": req.destination,
        "departure_date": req.departure_date.isoformat(),
        "return_date": req.return_date.isoformat() if req.return_date else None,
        "return_origin": req.return_origin,
        "return_destination": req.return_destination,
        "passengers": req.passengers,
        "cabin_class": req.cabin_class,
        "max_stops": req.max_stops,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return f"flightdeck:offers:{digest}"


def _offer_to_jsonable(n: NormalizedOffer) -> dict:
    d = asdict(n)
    for seg in d["segments"]:
        seg["depart_at"] = seg["depart_at"].isoformat()
        seg["arrive_at"] = seg["arrive_at"].isoformat()
        seg["duration"] = seg["duration"].total_seconds()
    d["price_usd"] = str(d["price_usd"])
    d["total_duration"] = d["total_duration"].total_seconds()
    d["expires_at"] = d["expires_at"].isoformat() if d["expires_at"] else None
    return d


def _offer_from_jsonable(d: dict) -> NormalizedOffer:
    segments = [
        Segment(
            carrier=s["carrier"],
            flight_no=s["flight_no"],
            origin=s["origin"],
            destination=s["destination"],
            depart_at=datetime.fromisoformat(s["depart_at"]),
            arrive_at=datetime.fromisoformat(s["arrive_at"]),
            duration=timedelta(seconds=s["duration"]),
            cabin=s["cabin"],
        )
        for s in d["segments"]
    ]
    return NormalizedOffer(
        source=d["source"],
        source_id=d["source_id"],
        price_usd=Decimal(d["price_usd"]),
        currency=d["currency"],
        total_duration=timedelta(seconds=d["total_duration"]),
        stops=d["stops"],
        segments=segments,
        fare_type=d["fare_type"],
        booking_url=d["booking_url"],
        deep_link=d["deep_link"],
        expires_at=datetime.fromisoformat(d["expires_at"]) if d["expires_at"] else None,
        raw=d["raw"],
        leg=d.get("leg"),
    )


async def _fan_out_one_call(req: SearchRequest) -> list[NormalizedOffer]:
    """Run all configured sources in parallel for a single provider call each."""
    results = await asyncio.gather(
        _search_amadeus(req),
        _search_kiwi(req),
        _search_serpapi(req),
        return_exceptions=False,  # already swallowed inside each helper
    )
    flat: list[NormalizedOffer] = []
    for source_offers in results:
        flat.extend(source_offers)
    return flat


def _open_jaw_leg_requests(req: SearchRequest) -> tuple[SearchRequest, SearchRequest]:
    """Split an open-jaw request into two one-way legs.

    None of Amadeus/Kiwi/SerpAPI's wired-up search endpoints accept an
    independent return-leg origin/destination in a single round-trip call —
    each only supports a symmetric there-and-back. So an open-jaw request
    (return_origin/return_destination set to something other than the
    outbound destination/origin) is priced as two separate one-way fares,
    tagged via NormalizedOffer.leg so callers can tell them apart.
    """
    no_return = {"return_date": None, "return_origin": None, "return_destination": None}
    outbound_req = req.model_copy(update=no_return)
    return_req = req.model_copy(update={
        "origin": req.return_origin or req.destination,
        "destination": req.return_destination or req.origin,
        "departure_date": req.return_date,
        **no_return,
    })
    return outbound_req, return_req


async def _fan_out_sources(req: SearchRequest) -> list[NormalizedOffer]:
    """Run all configured sources in parallel; flatten the results.

    Cached for a short TTL, keyed on the search params, so duplicate/rapid-fire
    identical searches (a watch re-check, a deal scan re-hitting the same date)
    don't re-hit every provider.
    """

    async def _live_fetch() -> list[dict]:
        if req.is_open_jaw:
            outbound_req, return_req = _open_jaw_leg_requests(req)
            outbound_offers, return_offers = await asyncio.gather(
                _fan_out_one_call(outbound_req), _fan_out_one_call(return_req)
            )
            flat = (
                [replace(o, leg="outbound") for o in outbound_offers]
                + [replace(o, leg="return") for o in return_offers]
            )
        else:
            flat = await _fan_out_one_call(req)
        return [_offer_to_jsonable(o) for o in flat]

    cached = await get_or_set(_offers_cache_key(req), _OFFERS_CACHE_TTL_SECONDS, _live_fetch)
    return [_offer_from_jsonable(d) for d in cached]


# Nearby expansion: cap the number of (origin, destination) pairs a single
# search can fan out to — each pair costs one query per source.
MAX_NEARBY_COMBOS = 4


async def _expand_route(session: AsyncSession, req: SearchRequest) -> list[tuple[str, str]]:
    """(origin, destination) pairs for the search, honoring include_nearby.

    Airports are geo-expanded by lat/lon distance (see services.geo); the
    requested pair always comes first, alternates follow closest-first.
    """
    if not req.include_nearby:
        return [(req.origin, req.destination)]
    origins = await expand_airport(session, req.origin)
    dests = await expand_airport(session, req.destination)
    combos = [(o, d) for o in origins for d in dests if o != d]
    primary = (req.origin, req.destination)
    if primary in combos:
        combos.remove(primary)
    return [primary, *combos][:MAX_NEARBY_COMBOS]


async def _fan_out_combos(session: AsyncSession, req: SearchRequest) -> list[NormalizedOffer]:
    """Fan out across sources AND nearby-airport pairs, concurrently."""
    combos = await _expand_route(session, req)
    reqs = [
        req.model_copy(update={"origin": o, "destination": d, "include_nearby": False})
        for o, d in combos
    ]
    results = await asyncio.gather(*[_fan_out_sources(r) for r in reqs])
    return [offer for source_offers in results for offer in source_offers]


def _to_db_offer(search_id, n: NormalizedOffer) -> FlightOffer:
    return FlightOffer(
        search_id=search_id,
        source=n.source,
        price_usd=n.price_usd,
        currency=n.currency,
        total_duration=n.total_duration,
        stops=n.stops,
        segments=[
            {
                "carrier": s.carrier,
                "flight_no": s.flight_no,
                "origin": s.origin,
                "destination": s.destination,
                "depart_at": s.depart_at.isoformat(),
                "arrive_at": s.arrive_at.isoformat(),
                "duration_seconds": int(s.duration.total_seconds()),
                "cabin": s.cabin,
            }
            for s in n.segments
        ],
        fare_type=n.fare_type,
        booking_url=n.booking_url,
        deep_link=n.deep_link,
        expires_at=n.expires_at,
        leg=n.leg,
    )


async def run_search(
    session: AsyncSession,
    req: SearchRequest,
    prefs: RankingPreferences | None = None,
) -> tuple[Search, Sequence[FlightOffer]]:
    """Persist a Search row, fan out to sources, dedup, rank, persist offers.

    Returns offers sorted by `score_offer` (lower = better).
    """
    prefs = prefs or RankingPreferences()

    search = Search(
        origin=req.origin,
        destination=req.destination,
        departure_date=req.departure_date,
        return_date=req.return_date,
        return_origin=req.return_origin,
        return_destination=req.return_destination,
        flex_days=req.flex_days,
        passengers=req.passengers,
        cabin_class=req.cabin_class,
        include_nearby=req.include_nearby,
    )
    session.add(search)
    await session.flush()  # populate search.id

    # Fan out to Amadeus + Kiwi + SerpAPI in parallel — and across nearby
    # airport pairs when include_nearby is set. Failed sources are logged
    # and skipped, never block the response.
    normalized: list[NormalizedOffer] = await _fan_out_combos(session, req)

    # Dedup across sources, then rank via the user's score_offer hook
    deduped = dedupe_offers(normalized)
    cheapest = min((d.offer.price_usd for d in deduped), default=None)
    scored = [score_offer(d.offer, prefs, cheapest_price=cheapest) for d in deduped]
    scored.sort(key=lambda s: s.score)

    db_offers = [_to_db_offer(search.id, s.offer) for s in scored]
    session.add_all(db_offers)
    await session.commit()

    for o in db_offers:
        await session.refresh(o)
    return search, db_offers
