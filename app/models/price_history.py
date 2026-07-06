from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class PriceHistory(Base, UUIDMixin):
    """Append-only price observations.

    `route_key`: 'SFO-NRT' for any-date or 'SFO-NRT:2026-04-15' for date-pinned.
    `days_until_departure`: enables advance-purchase-curve analysis.
    """

    __tablename__ = "price_history"

    route_key: Mapped[str] = mapped_column(String, nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    cabin_class: Mapped[str] = mapped_column(String, default="economy", nullable=False)
    days_until_departure: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_price_history_route", "route_key", "recorded_at"),
        Index("idx_price_history_departure", "route_key", "days_until_departure"),
    )
