"""Load points programs and their transfer partners from data/transfer_partners.json.

Idempotent — re-running updates `transfer_partners` and `card_name`, but preserves
the user's `balance` if a row already exists.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import session_scope
from app.models import PointsProgram

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "transfer_partners.json"


def _load_rows() -> list[dict]:
    with DATA_FILE.open() as f:
        payload = json.load(f)
    return [
        {
            "program_name": p["program_name"],
            "card_name": p.get("card_name"),
            "transfer_partners": p["transfer_partners"],
            "balance": 0,
        }
        for p in payload["programs"]
    ]


async def seed() -> int:
    rows = _load_rows()
    async with session_scope() as session:
        stmt = pg_insert(PointsProgram).values(rows)
        # Preserve balance on conflict — user has set it; only refresh metadata
        stmt = stmt.on_conflict_do_update(
            index_elements=["program_name"],
            set_={
                "card_name": stmt.excluded.card_name,
                "transfer_partners": stmt.excluded.transfer_partners,
            },
        )
        await session.execute(stmt)
        await session.commit()
    return len(rows)


if __name__ == "__main__":
    count = asyncio.run(seed())
    print(f"Seeded {count} points programs.")
