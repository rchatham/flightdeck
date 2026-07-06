"""Multi-source offer deduplication.

Two offers from different aggregators may be the same physical flight at
different prices. We collapse them by `dedup_key` (carrier + flight# + depart
time per segment) and keep the cheapest, while remembering all sources for
attribution.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.integrations.types import NormalizedOffer


@dataclass
class DedupedOffer:
    """The cheapest offer for a unique flight, plus a list of all sources that found it."""

    offer: NormalizedOffer
    sources: list[str] = field(default_factory=list)
    all_prices: dict[str, float] = field(default_factory=dict)


def dedupe_offers(offers: Iterable[NormalizedOffer]) -> list[DedupedOffer]:
    """Collapse offers by `dedup_key`. Keep the cheapest as canonical, record all sources."""
    bucket: dict[str, DedupedOffer] = {}
    for o in offers:
        key = o.dedup_key
        if not key:  # skip offers without parseable segments
            continue
        if key not in bucket:
            bucket[key] = DedupedOffer(
                offer=o,
                sources=[o.source],
                all_prices={o.source: float(o.price_usd)},
            )
            continue

        existing = bucket[key]
        existing.all_prices[o.source] = float(o.price_usd)
        if o.source not in existing.sources:
            existing.sources.append(o.source)
        # Promote the cheaper offer to canonical
        if o.price_usd < existing.offer.price_usd:
            existing.offer = o
    return list(bucket.values())
