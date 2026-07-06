from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DECIMAL, Boolean, Date, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class PriceWatch(Base, UUIDMixin, TimestampMixin):
    """A specific trip the user wants tracked.

    Unlike `price_history` scraping (aggregate route intelligence), a watch is
    a concrete intent: this origin/destination on this date, alert me when the
    price is right. Rolling state columns are updated by the watch checker on
    every run so the alert rule can compare against what we've seen before.
    """

    __tablename__ = "price_watches"

    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), nullable=False)
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cabin_class: Mapped[str] = mapped_column(String, default="economy", nullable=False)
    target_price_usd: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Rolling state — written by the checker, read by the alert rule.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_price_usd: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), nullable=True)
    lowest_seen_usd: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), nullable=True)
    last_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_alerted_price_usd: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), nullable=True)

    __table_args__ = (
        Index("idx_price_watches_active", "active", "departure_date"),
    )


class PriceAlert(Base, UUIDMixin, TimestampMixin):
    """An alert fired by the watch checker. Append-only."""

    __tablename__ = "price_alerts"

    watch_id: Mapped[UUID] = mapped_column(
        ForeignKey("price_watches.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)  # AlertKind value
    price_usd: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    previous_price_usd: Mapped[Decimal | None] = mapped_column(DECIMAL(10, 2), nullable=True)
    message: Mapped[str] = mapped_column(String, nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("idx_price_alerts_watch", "watch_id", "created_at"),
    )
