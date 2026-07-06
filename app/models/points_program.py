from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class PointsProgram(Base, UUIDMixin):
    """User-owned points balances and transfer-partner mappings.

    Single-user MVP — one row per program (e.g., 'Chase Ultimate Rewards').
    `transfer_partners` is JSONB: [{airline, ratio, bonus_pct}, ...].
    """

    __tablename__ = "points_programs"

    program_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    card_name: Mapped[str | None] = mapped_column(String, nullable=True)
    transfer_partners: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
