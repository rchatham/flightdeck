"""Tests for geo helpers (pure functions — no DB)."""
from __future__ import annotations

from decimal import Decimal

from app.models import Airport
from app.services.geo import haversine_km, match_airports, parse_latlon, rank_nearby


def airport(code: str, city: str, lat: float | None, lon: float | None,
            name: str | None = None) -> Airport:
    return Airport(
        iata_code=code, name=name or f"{city} International Airport",
        city=city, country="US",
        latitude=Decimal(str(lat)) if lat is not None else None,
        longitude=Decimal(str(lon)) if lon is not None else None,
    )


BAY_AREA = [
    airport("SFO", "San Francisco", 37.6213, -122.3790),
    airport("OAK", "Oakland", 37.7213, -122.2207),
    airport("SJC", "San Jose", 37.3639, -121.9289),
    airport("LAX", "Los Angeles", 33.9425, -118.4081),
    airport("XXX", "Nowhere", None, None),  # no coordinates — must be skipped
]


def test_haversine_known_distance():
    # SFO ↔ LAX is ~543 km great-circle.
    d = haversine_km(37.6213, -122.3790, 33.9425, -118.4081)
    assert 520 <= d <= 560


def test_haversine_zero_for_same_point():
    assert haversine_km(37.62, -122.38, 37.62, -122.38) == 0


def test_parse_latlon_valid_and_invalid():
    assert parse_latlon("37.77,-122.42") == (37.77, -122.42)
    assert parse_latlon(" 37.77 , -122.42 ") == (37.77, -122.42)
    assert parse_latlon("SFO") is None
    assert parse_latlon("san francisco") is None
    assert parse_latlon("91,0") is None       # latitude out of range
    assert parse_latlon("0,181") is None      # longitude out of range


def test_rank_nearby_orders_by_distance_and_respects_radius():
    # Downtown SF: SFO (~17 km) edges out OAK (~19 km); SJC trails; LAX is
    # ~550 km away and outside the radius entirely.
    hits = rank_nearby(BAY_AREA, 37.7749, -122.4194, radius_km=100, limit=10)
    assert [h.airport.iata_code for h in hits] == ["SFO", "OAK", "SJC"]
    assert hits[0].distance_km < hits[1].distance_km < hits[2].distance_km


def test_rank_nearby_respects_limit():
    hits = rank_nearby(BAY_AREA, 37.7749, -122.4194, radius_km=1000, limit=2)
    assert len(hits) == 2


def test_rank_nearby_skips_airports_without_coordinates():
    hits = rank_nearby(BAY_AREA, 37.7749, -122.4194, radius_km=10000, limit=10)
    assert "XXX" not in [h.airport.iata_code for h in hits]


def test_match_airports_by_city_substring():
    assert [a.iata_code for a in match_airports(BAY_AREA, "san")] == ["SFO", "SJC"]
    assert [a.iata_code for a in match_airports(BAY_AREA, "OAKLAND")] == ["OAK"]
    assert match_airports(BAY_AREA, "tokyo") == []
    assert match_airports(BAY_AREA, "  ") == []
