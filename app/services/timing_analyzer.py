"""Timing analyzer service.

Reads from the `price_history` table to build summary stats (current price,
historical median/min/max, advance-purchase curve, day-of-week patterns) and
hands them to the `timing.recommend_booking_window` hook for the verdict.

Public entrypoints:
  • analyze_route(session, origin, destination, departure_date) → Recommendation
  • get_history(session, route_key, lookback_days) → list of price points
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PriceHistory
from app.services.timing import (
    PriceHistoryStats,
    PricePoint,
    Recommendation,
    recommend_booking_window,
)

logger = logging.getLogger(__name__)


def _route_key(origin: str, destination: str, departure_date: date | None = None) -> str:
    base = f"{origin.upper()}-{destination.upper()}"
    return f"{base}:{departure_date.isoformat()}" if departure_date else base


async def get_history(
    session: AsyncSession, route_key: str, lookback_days: int = 180
) -> list[PriceHistory]:
    """Return raw price-history rows for `route_key`, oldest first."""
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    stmt = (
        select(PriceHistory)
        .where(PriceHistory.route_key == route_key)
        .where(PriceHistory.recorded_at >= cutoff)
        .order_by(PriceHistory.recorded_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


def _to_pricepoints(rows: Sequence[PriceHistory]) -> list[PricePoint]:
    return [
        PricePoint(
            recorded_at=r.recorded_at,
            price_usd=r.price_usd,
            days_until_departure=r.days_until_departure,
        )
        for r in rows
    ]


def _compute_stats(history: list[PricePoint], current_price: Decimal | None) -> PriceHistoryStats:
    """Aggregate raw price points into summary stats for the hook."""
    if not history:
        return PriceHistoryStats(
            sample_count=0,
            current_price=current_price,
            median_price=None,
            min_price=None,
            max_price=None,
            current_pct_above_median=None,
            history=[],
        )
    prices = sorted([float(p.price_usd) for p in history])
    n = len(prices)
    median = Decimal(str(prices[n // 2])) if n % 2 == 1 else \
        Decimal(str((prices[n // 2 - 1] + prices[n // 2]) / 2))
    cur_pct = None
    if current_price is not None and median > 0:
        cur_pct = float((current_price - median) / median) * 100.0
    return PriceHistoryStats(
        sample_count=n,
        current_price=current_price,
        median_price=median,
        min_price=Decimal(str(prices[0])),
        max_price=Decimal(str(prices[-1])),
        current_pct_above_median=cur_pct,
        history=history,
    )


async def analyze_route(
    session: AsyncSession,
    origin: str,
    destination: str,
    departure_date: date,
    current_price: Decimal | None = None,
    lookback_days: int = 180,
) -> Recommendation:
    """Run the timing analysis for one route + travel date."""
    route_key = _route_key(origin, destination, departure_date)
    rows = await get_history(session, route_key, lookback_days=lookback_days)

    # Fall back to all-date history if no date-pinned rows exist
    if not rows:
        rows = await get_history(session, _route_key(origin, destination), lookback_days)

    history = _to_pricepoints(rows)
    days_until = (departure_date - date.today()).days
    stats = _compute_stats(history, current_price)
    return recommend_booking_window(stats, days_until_departure=days_until)
