"""Load airports from data/airports.csv into the airports table.

Also enriches each airport row with `nearby_airports` from data/nearby_airports.json
so the route optimizer can expand single-airport queries into city-wide groups.
"""
from __future__ import annotations

import asyncio
import csv
import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import session_scope
from app.models import Airport

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
AIRPORTS_CSV = DATA_DIR / "airports.csv"
NEARBY_JSON = DATA_DIR / "nearby_airports.json"


def _load_nearby_map() -> dict[str, list[str]]:
    """Build {iata: [other_codes_in_same_group]} from the city-group file."""
    with NEARBY_JSON.open() as f:
        groups = json.load(f)["groups"]
    nearby: dict[str, list[str]] = {}
    for codes in groups.values():
        for code in codes:
            nearby[code] = [c for c in codes if c != code]
    return nearby


def _load_airport_rows() -> list[dict]:
    nearby = _load_nearby_map()
    rows: list[dict] = []
    with AIRPORTS_CSV.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "iata_code": row["iata_code"],
                "name": row["name"],
                "city": row["city"],
                "country": row["country"],
                "latitude": Decimal(row["latitude"]) if row["latitude"] else None,
                "longitude": Decimal(row["longitude"]) if row["longitude"] else None,
                "timezone": row["timezone"] or None,
                "nearby_airports": nearby.get(row["iata_code"], []),
            })
    return rows


async def seed() -> int:
    rows = _load_airport_rows()
    async with session_scope() as session:
        # Upsert: insert, on conflict update mutable fields
        stmt = pg_insert(Airport).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["iata_code"],
            set_={
                "name": stmt.excluded.name,
                "city": stmt.excluded.city,
                "country": stmt.excluded.country,
                "latitude": stmt.excluded.latitude,
                "longitude": stmt.excluded.longitude,
                "timezone": stmt.excluded.timezone,
                "nearby_airports": stmt.excluded.nearby_airports,
            },
        )
        await session.execute(stmt)
        await session.commit()
    return len(rows)


if __name__ == "__main__":
    count = asyncio.run(seed())
    print(f"Seeded {count} airports.")
