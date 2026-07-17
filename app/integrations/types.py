"""Common offer shape returned by all flight-search integrations.

Each integration (Amadeus, Kiwi, SerpAPI) maps its native response onto these
dataclasses so downstream code can compare offers from different sources without
caring where they came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass
class Segment:
    """A single flight leg."""

    carrier: str            # IATA airline code, e.g., "UA"
    flight_no: str          # e.g., "837"
    origin: str             # IATA airport code
    destination: str        # IATA airport code
    depart_at: datetime
    arrive_at: datetime
    duration: timedelta
    cabin: str = "economy"  # economy, premium_economy, business, first


@dataclass
class NormalizedOffer:
    """A flight offer in a source-agnostic shape.

    `source_id` is the unique ID from the originating source (Amadeus offer ID,
    Kiwi booking_token, etc.). Used for deep-link booking and dedup.
    """

    source: str             # 'amadeus', 'kiwi', 'serpapi'
    source_id: str
    price_usd: Decimal
    currency: str
    total_duration: timedelta
    stops: int
    segments: list[Segment] = field(default_factory=list)
    fare_type: str = "regular"   # 'regular', 'hidden_city', 'split_ticket', 'multi_city'
    booking_url: str | None = None
    deep_link: str | None = None
    expires_at: datetime | None = None
    raw: dict | None = None      # original source payload (kept for debugging)
    leg: str | None = None       # 'outbound' or 'return' — open-jaw searches only

    @property
    def dedup_key(self) -> str:
        """Identify the same physical flight across sources.

        Same carrier + flight number + departure datetime → same flight.
        Multi-segment itineraries: join all leg keys with `|`.
        """
        parts = [
            f"{s.carrier}{s.flight_no}@{s.depart_at.isoformat(timespec='minutes')}"
            for s in self.segments
        ]
        return "|".join(parts)
