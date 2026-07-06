from decimal import Decimal

from sqlalchemy import ARRAY, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Airport(Base):
    __tablename__ = "airports"

    iata_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    city: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(nullable=True)
    timezone: Mapped[str | None] = mapped_column(String, nullable=True)
    nearby_airports: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(3)), nullable=True
    )
