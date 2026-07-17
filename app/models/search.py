from datetime import date

from sqlalchemy import Boolean, Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Search(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "searches"

    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), nullable=False)
    departure_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Open-jaw: return leg departs/arrives different airports than the
    # outbound. Null means "same as origin/destination" (a normal round trip).
    return_origin: Mapped[str | None] = mapped_column(String(3), nullable=True)
    return_destination: Mapped[str | None] = mapped_column(String(3), nullable=True)
    flex_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passengers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cabin_class: Mapped[str] = mapped_column(String, default="economy", nullable=False)
    include_nearby: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
