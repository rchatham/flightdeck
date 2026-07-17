from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DECIMAL, DateTime, ForeignKey, Integer, Interval, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class FlightOffer(Base, UUIDMixin, TimestampMixin):
    """A single flight offer returned by an external source.

    `segments` is a JSONB list of flight legs:
      [{carrier, flight_no, origin, dest, depart_at, arrive_at, duration, cabin}, ...]
    """

    __tablename__ = "flight_offers"

    search_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("searches.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    total_duration: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    stops: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    segments: Mapped[list] = mapped_column(JSONB, nullable=False)
    fare_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set for open-jaw searches only: "outbound" or "return". Null for a
    # normal (symmetric) round-trip or one-way offer priced in one call.
    leg: Mapped[str | None] = mapped_column(String, nullable=True)
    booking_url: Mapped[str | None] = mapped_column(String, nullable=True)
    deep_link: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
