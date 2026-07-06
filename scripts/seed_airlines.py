"""Load major carriers from data/airlines.json.

Idempotent — re-running refreshes name/alliance/URLs on conflict.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import session_scope
from app.models import Airline

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "airlines.json"


def _load_rows() -> list[dict]:
    with DATA_FILE.open() as f:
        payload = json.load(f)
    return [
        {
            "iata_code": a["iata_code"],
            "name": a["name"],
            "alliance": a.get("alliance"),
            "is_regional": False,
            "direct_booking_url": a.get("direct_booking_url"),
            "loyalty_program": a.get("loyalty_program"),
        }
        for a in payload["airlines"]
    ]


async def seed() -> int:
    rows = _load_rows()
    async with session_scope() as session:
        stmt = pg_insert(Airline).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["iata_code"],
            set_={
                "name": stmt.excluded.name,
                "alliance": stmt.excluded.alliance,
                "direct_booking_url": stmt.excluded.direct_booking_url,
                "loyalty_program": stmt.excluded.loyalty_program,
            },
        )
        await session.execute(stmt)
        await session.commit()
    return len(rows)


if __name__ == "__main__":
    count = asyncio.run(seed())
    print(f"Seeded {count} airlines.")
