"""Geo utilities — airport resolution and nearby-airport lookup by lat/lon.

A "location" anywhere in the API can be:
  • an IATA code            "SFO"
  • a "lat,lon" pair        "37.77,-122.42"
  • a city or airport name  "san francisco", "tokyo", "heathrow"

Resolution anchors the query to coordinates, then finds airports within a
radius by haversine distance. The seeded airport table is ~100 rows, so
distance math happens in Python — no PostGIS required.

Pure helpers (`haversine_km`, `parse_latlon`, `rank_nearby`, `match_airports`)
take plain data and are unit-tested without a database; the async wrappers
own the session.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Airport

DEFAULT_RADIUS_KM = 150.0
DEFAULT_LIMIT = 6

_LATLON_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometers."""
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = rlat2 - rlat1, rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def parse_latlon(query: str) -> tuple[float, float] | None:
    """'37.77,-122.42' → (37.77, -122.42); None if not a coordinate pair."""
    m = _LATLON_RE.match(query)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


@dataclass
class AirportHit:
    airport: Airport
    distance_km: float


@dataclass
class ResolvedLocation:
    """A location query resolved to concrete airports."""

    query: str
    kind: str                      # 'iata' | 'latlon' | 'name'
    label: str                     # human description, e.g. "San Francisco (SFO)"
    anchor: tuple[float, float] | None
    airports: list[AirportHit] = field(default_factory=list)

    @property
    def codes(self) -> list[str]:
        return [h.airport.iata_code for h in self.airports]


def rank_nearby(
    airports: list[Airport],
    lat: float,
    lon: float,
    *,
    radius_km: float = DEFAULT_RADIUS_KM,
    limit: int = DEFAULT_LIMIT,
) -> list[AirportHit]:
    """Airports within `radius_km` of a point, closest first."""
    hits = [
        AirportHit(a, haversine_km(lat, lon, float(a.latitude), float(a.longitude)))
        for a in airports
        if a.latitude is not None and a.longitude is not None
    ]
    hits = [h for h in hits if h.distance_km <= radius_km]
    hits.sort(key=lambda h: h.distance_km)
    return hits[:limit]


def match_airports(airports: list[Airport], query: str) -> list[Airport]:
    """Case-insensitive substring match on city and airport name."""
    q = query.strip().lower()
    if not q:
        return []
    return [
        a for a in airports
        if q in a.city.lower() or q in a.name.lower()
    ]


async def _all_airports(session: AsyncSession) -> list[Airport]:
    return list((await session.execute(select(Airport))).scalars().all())


async def resolve_location(
    session: AsyncSession,
    query: str,
    *,
    radius_km: float = DEFAULT_RADIUS_KM,
    limit: int = DEFAULT_LIMIT,
) -> ResolvedLocation:
    """Resolve a free-form location to airports, nearest first.

    IATA codes and name matches are anchored to the matched airport's
    coordinates and then expanded to neighbors within `radius_km` (the
    match itself always ranks first at 0 km... or its true distance).
    Pass radius_km=0 to disable expansion and get exact matches only.

    The seeded airport table covers ~100 major hubs, not the ~7,000 IATA
    codes that exist worldwide. A query shaped like a code (3 letters) but
    absent from the table falls through as an unverified bare code rather
    than failing outright — the fare sources can still search it, they just
    won't get geo-expanded to neighbors since we don't know their location.
    """
    q = query.strip()
    airports = await _all_airports(session)
    by_code = {a.iata_code: a for a in airports}

    # 1. Coordinates
    latlon = parse_latlon(q)
    if latlon is not None:
        lat, lon = latlon
        return ResolvedLocation(
            query=query, kind="latlon", label=f"({lat:.3f}, {lon:.3f})",
            anchor=latlon,
            airports=rank_nearby(airports, lat, lon, radius_km=max(radius_km, 1.0), limit=limit),
        )

    # 2. Exact IATA code
    code = q.upper()
    if len(code) == 3 and code.isalpha() and code in by_code:
        a = by_code[code]
        if a.latitude is None or radius_km <= 0:
            return ResolvedLocation(
                query=query, kind="iata", label=f"{a.city} ({a.iata_code})",
                anchor=None, airports=[AirportHit(a, 0.0)],
            )
        lat, lon = float(a.latitude), float(a.longitude)
        return ResolvedLocation(
            query=query, kind="iata", label=f"{a.city} ({a.iata_code})",
            anchor=(lat, lon),
            airports=rank_nearby(airports, lat, lon, radius_km=radius_km, limit=limit),
        )

    # 3. City / airport-name substring
    matches = match_airports(airports, q)
    if not matches:
        # 4. Last resort: shaped like an IATA code, just not one we've
        #    seeded. Let it through unverified rather than blocking every
        #    airport outside our curated ~100-row reference table.
        if len(code) == 3 and code.isalpha():
            placeholder = Airport(
                iata_code=code, city=code, country="??",
                name="Unverified — not in FlightDeck's airport reference data",
            )
            return ResolvedLocation(
                query=query, kind="iata_unverified", label=f"{code} (unverified)",
                anchor=None, airports=[AirportHit(placeholder, 0.0)],
            )
        return ResolvedLocation(query=query, kind="name", label=query, anchor=None)
    anchor_airport = next((m for m in matches if m.latitude is not None), None)
    if anchor_airport is None or radius_km <= 0:
        return ResolvedLocation(
            query=query, kind="name", label=f"{matches[0].city}",
            anchor=None, airports=[AirportHit(m, 0.0) for m in matches[:limit]],
        )
    lat, lon = float(anchor_airport.latitude), float(anchor_airport.longitude)
    hits = rank_nearby(airports, lat, lon, radius_km=radius_km, limit=limit)
    # Direct name matches always make the cut, even just outside the radius.
    hit_codes = {h.airport.iata_code for h in hits}
    for m in matches:
        if m.iata_code not in hit_codes and m.latitude is not None:
            dist = haversine_km(lat, lon, float(m.latitude), float(m.longitude))
            hits.append(AirportHit(m, dist))
    hits.sort(key=lambda h: h.distance_km)
    return ResolvedLocation(
        query=query, kind="name", label=f"{anchor_airport.city}",
        anchor=(lat, lon), airports=hits[:limit],
    )


async def expand_airport(
    session: AsyncSession,
    code: str,
    *,
    radius_km: float = 100.0,
    limit: int = 3,
) -> list[str]:
    """IATA code → [itself + geo-neighbors], for nearby-airport search fan-out.

    Falls back to the seeded `nearby_airports` array when the airport has no
    coordinates, and to just [code] when it's unknown entirely.
    """
    resolved = await resolve_location(session, code, radius_km=radius_km, limit=limit)
    if resolved.codes:
        codes = resolved.codes
        if code.upper() in codes:  # matched airport should lead the list
            codes = [code.upper()] + [c for c in codes if c != code.upper()]
        return codes
    airport = await session.get(Airport, code.upper())
    if airport is not None and airport.nearby_airports:
        return [code.upper(), *airport.nearby_airports][:limit]
    return [code.upper()]
