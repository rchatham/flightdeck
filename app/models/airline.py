from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Airline(Base):
    __tablename__ = "airlines"

    iata_code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    alliance: Mapped[str | None] = mapped_column(String, nullable=True)
    is_regional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    direct_booking_url: Mapped[str | None] = mapped_column(String, nullable=True)
    loyalty_program: Mapped[str | None] = mapped_column(String, nullable=True)
