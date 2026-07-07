"""Deal scanning — find the cheapest days to fly between two *locations*.

A scan takes two location queries (IATA code, city name, or "lat,lon"),
resolves each to a small set of nearby airports, samples departure dates
across a window, and fans out live searches over the (origin, destination,
date) grid. Results answer three questions at once:

  • Which DAY is cheapest to leave?          (per-date bests, sorted)
  • Which AIRPORT PAIR is cheapest?          (nearby expansion on both ends)
  • Is the price actually a deal?            (vs. price-history median:
                                              DEAL ≤ -20%, GOOD ≤ -10%)

Optionally the best find is run through hidden-fare discovery (Hook 3) to
surface hacker fares — hidden-city / split-ticket routings — with risk
levels attached.

Every scanned price is appended to `price_history`, so deal scans feed the
timing analyzer the same way the nightly scraper does.

API-quota control: `max_searches` caps the total number of fan-outs. The
grid is trimmed by sampling dates evenly (endpoints always included) after
airport pairs are capped, and fan-outs run under a small semaphore.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from itertools import product
from statistics import median as stat_median

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.search import SearchRequest
from app.integrations.types import NormalizedOffer
from app.models import Airline, PriceHistory
from app.services.booking import BookingLink, google_flights_url
from app.services.fare_discovery import FareOpportunity, discover_opportunities
from app.services.fare_risks import FareStrategy
from app.services.geo import ResolvedLocation, resolve_location
from app.services.route_optimizer import _fan_out_sources

logger = logging.getLogger(__name__)

MAX_AIRPORTS_PER_SIDE = 3
MAX_WINDOW_DAYS = 90
DEAL_PCT = -20.0     # ≤ 20% below median → DEAL
GOOD_PCT = -10.0     # ≤ 10% below median → GOOD
_CONCURRENCY = 4


# --- Pure helpers (unit-tested without a DB) ---------------------------------


def sample_dates(date_from: date, date_to: date, max_n: int) -> list[date]:
    """Up to `max_n` dates across [date_from, date_to], endpoints included,
    spaced as evenly as possible."""
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    span = (date_to - date_from).days
    if max_n <= 1 or span == 0:
        return [date_from]
    n = min(max_n, span + 1)
    step = span / (n - 1)
    days = sorted({round(i * step) for i in range(n)})
    return [date_from + timedelta(days=d) for d in days]


def deal_tier(vs_median_pct: float | None) -> str | None:
    if vs_median_pct is None:
        return None
    if vs_median_pct <= DEAL_PCT:
        return "DEAL"
    if vs_median_pct <= GOOD_PCT:
        return "GOOD"
    return None


def compute_median(prices: list[Decimal]) -> Decimal | None:
    return Decimal(str(stat_median([float(p) for p in prices]))) if prices else None


# --- Result shapes ------------------------------------------------------------


@dataclass
class DateBest:
    """Cheapest option found for one departure date (across airport pairs)."""

    departure_date: date
    return_date: date | None
    origin: str
    destination: str
    price_usd: Decimal
    source: str
    stops: int
    deep_link: str | None
    vs_median_pct: float | None = None
    tier: str | None = None


@dataclass
class DealScanResult:
    origin: ResolvedLocation
    destination: ResolvedLocation
    date_from: date
    date_to: date
    searches_run: int
    dates_sampled: int
    median_price_usd: Decimal | None
    by_date: list[DateBest] = field(default_factory=list)   # chronological
    best: DateBest | None = None
    booking_links: list[BookingLink] = field(default_factory=list)
    opportunities: list[FareOpportunity] = field(default_factory=list)


# --- Scan ----------------------------------------------------------------------


async def _historical_median(
    session: AsyncSession, pairs: list[tuple[str, str]]
) -> Decimal | None:
    """Median of all stored observations for any of the airport pairs."""
    prefixes = [f"{o}-{d}" for o, d in pairs]
    conds = [PriceHistory.route_key.like(p + "%") for p in prefixes]
    stmt = select(PriceHistory.price_usd).where(or_(*conds))
    prices = list((await session.execute(stmt)).scalars().all())
    return compute_median(prices)


async def _best_booking_links(
    session: AsyncSession, best: DateBest, offer: NormalizedOffer | None
) -> list[BookingLink]:
    links: list[BookingLink] = []
    carrier = offer.segments[0].carrier if offer and offer.segments else ""
    airline = await session.get(Airline, carrier) if carrier else None
    if airline is not None and airline.direct_booking_url:
        note = "Booking direct gives the strongest schedule-change protection"
        if airline.loyalty_program:
            note += f" and {airline.loyalty_program} credit"
        links.append(BookingLink(
            kind="airline_direct", label=f"Book direct with {airline.name}",
            url=airline.direct_booking_url, note=note + ".",
        ))
    if best.deep_link:
        links.append(BookingLink(
            kind="source", label=f"Book this exact fare via {best.source}",
            url=best.deep_link,
            note=f"The ${float(best.price_usd):,.0f} price was quoted here; "
                 "re-verify before paying.",
        ))
    links.append(BookingLink(
        kind="google_flights",
        label=f"Google Flights: {best.origin}→{best.destination}",
        url=google_flights_url(best.origin, best.destination,
                               best.departure_date, best.return_date),
        note="Cross-check the price and alternative itineraries.",
    ))
    return links


async def scan_deals(
    session: AsyncSession,
    *,
    origin_query: str,
    destination_query: str,
    date_from: date,
    date_to: date,
    trip_length_days: int | None = None,
    cabin_class: str = "economy",
    max_searches: int = 12,
    include_nearby: bool = True,
    include_hacker_fares: bool = False,
) -> DealScanResult:
    """Scan the (airports × dates) grid for the cheapest days to fly."""
    date_to = min(date_to, date_from + timedelta(days=MAX_WINDOW_DAYS))
    radius = 150.0 if include_nearby else 0.0

    origin = await resolve_location(session, origin_query, radius_km=radius,
                                    limit=MAX_AIRPORTS_PER_SIDE)
    destination = await resolve_location(session, destination_query, radius_km=radius,
                                         limit=MAX_AIRPORTS_PER_SIDE)
    if not origin.codes or not destination.codes:
        missing = origin_query if not origin.codes else destination_query
        raise LookupError(f"could not resolve '{missing}' to any known airport")

    pairs = [(o, d) for o, d in product(origin.codes, destination.codes) if o != d]
    if not pairs:
        raise LookupError("origin and destination resolve to the same airport(s)")

    dates_budget = max(1, max_searches // len(pairs))
    dates = sample_dates(date_from, date_to, dates_budget)

    median = await _historical_median(session, pairs)  # BEFORE recording new rows

    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _one(o: str, d: str, dep: date) -> tuple[str, str, date, NormalizedOffer | None]:
        ret = dep + timedelta(days=trip_length_days) if trip_length_days else None
        req = SearchRequest(origin=o, destination=d, departure_date=dep,
                            return_date=ret, passengers=1,
                            cabin_class=cabin_class, include_nearby=False)
        async with sem:
            try:
                offers = await _fan_out_sources(req)
            except Exception as e:  # noqa: BLE001 — one bad combo shouldn't kill the scan
                logger.warning("deal scan combo %s-%s %s failed: %s", o, d, dep, e)
                return (o, d, dep, None)
        return (o, d, dep, min(offers, key=lambda x: x.price_usd) if offers else None)

    tasks = [_one(o, d, dep) for dep in dates for o, d in pairs]
    results = await asyncio.gather(*tasks)

    # Record observations + fold to per-date bests.
    best_offer_by_date: dict[date, tuple[DateBest, NormalizedOffer]] = {}
    for o, d, dep, offer in results:
        if offer is None:
            continue
        session.add(PriceHistory(
            route_key=f"{o}-{d}:{dep.isoformat()}",
            price_usd=offer.price_usd, source=offer.source,
            cabin_class=cabin_class,
            days_until_departure=(dep - date.today()).days,
        ))
        candidate = DateBest(
            departure_date=dep,
            return_date=dep + timedelta(days=trip_length_days) if trip_length_days else None,
            origin=o, destination=d, price_usd=offer.price_usd,
            source=offer.source, stops=offer.stops, deep_link=offer.deep_link,
        )
        held = best_offer_by_date.get(dep)
        if held is None or candidate.price_usd < held[0].price_usd:
            best_offer_by_date[dep] = (candidate, offer)
    await session.commit()

    by_date = [db for db, _ in
               (best_offer_by_date[k] for k in sorted(best_offer_by_date))]
    for db_ in by_date:
        if median and median > 0:
            db_.vs_median_pct = float((db_.price_usd - median) / median) * 100.0
            db_.tier = deal_tier(db_.vs_median_pct)

    best = min(by_date, key=lambda b: b.price_usd, default=None)
    result = DealScanResult(
        origin=origin, destination=destination,
        date_from=date_from, date_to=date_to,
        searches_run=len(tasks), dates_sampled=len(dates),
        median_price_usd=median, by_date=by_date, best=best,
    )
    if best is not None:
        best_offer = best_offer_by_date[best.departure_date][1]
        result.booking_links = await _best_booking_links(session, best, best_offer)
        if include_hacker_fares:
            req = SearchRequest(origin=best.origin, destination=best.destination,
                                departure_date=best.departure_date,
                                return_date=best.return_date, passengers=1,
                                cabin_class=cabin_class, include_nearby=False)
            try:
                result.opportunities = await discover_opportunities(
                    req, [FareStrategy.HIDDEN_CITY, FareStrategy.SPLIT_TICKET]
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("hacker-fare discovery failed: %s", e)
    return result
