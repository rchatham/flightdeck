"""SQLAlchemy models for FlightDeck.

Single-user MVP — no users table or user_id FKs. Re-add them when introducing auth.
"""
from app.models.airline import Airline
from app.models.airport import Airport
from app.models.base import Base
from app.models.offer import FlightOffer
from app.models.points_program import PointsProgram
from app.models.price_history import PriceHistory
from app.models.search import Search
from app.models.watch import PriceAlert, PriceWatch

__all__ = [
    "Base",
    "Airport",
    "Airline",
    "Search",
    "FlightOffer",
    "PriceHistory",
    "PointsProgram",
    "PriceWatch",
    "PriceAlert",
]
