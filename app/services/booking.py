"""Booking handoff — turn offers and watches into actionable booking links.

FlightDeck deliberately does not issue tickets (PNR creation needs airline
consolidator agreements and payment handling). Instead it hands the user the
best places to complete the purchase, ordered by protection quality:

  1. airline_direct   — booking direct keeps you in one PNR with the carrier:
                        best schedule-change handling, loyalty credit, and no
                        OTA middleman when things go wrong.
  2. source           — the exact priced offer's deep link (Kiwi/Amadeus/…).
                        Cheapest path to *this* fare, but OTA support quality
                        varies.
  3. google_flights   — price verification and a second routing opinion.

All builders are pure functions over model data — no I/O — so the API layer
owns the lookups and tests need no database.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from urllib.parse import quote

from app.models import Airline, FlightOffer, Search

GOOGLE_FLIGHTS_BASE = "https://www.google.com/travel/flights"


@dataclass
class BookingLink:
    kind: str      # 'airline_direct' | 'source' | 'google_flights'
    label: str
    url: str
    note: str = ""


def google_flights_url(
    origin: str,
    destination: str,
    departure_date: date,
    return_date: date | None = None,
) -> str:
    q = f"Flights from {origin} to {destination} on {departure_date.isoformat()}"
    if return_date is not None:
        q += f" through {return_date.isoformat()}"
    return f"{GOOGLE_FLIGHTS_BASE}?q={quote(q)}"


def build_route_links(
    origin: str,
    destination: str,
    departure_date: date,
    return_date: date | None = None,
) -> list[BookingLink]:
    """Links for a route with no specific offer (e.g. from a watch alert)."""
    return [
        BookingLink(
            kind="google_flights",
            label=f"Google Flights: {origin}→{destination}",
            url=google_flights_url(origin, destination, departure_date, return_date),
            note="Compare current fares and pick an itinerary.",
        )
    ]


def _offer_route(
    offer: FlightOffer, search: Search | None
) -> tuple[str, str, date | None, date | None]:
    """Best-effort (origin, destination, departure, return) for an offer.

    Prefer the originating Search (authoritative for round-trips — segment
    lists fold the return leg back to the origin). Fall back to segments.
    """
    if search is not None and search.departure_date is not None:
        return (search.origin, search.destination, search.departure_date, search.return_date)
    segments = offer.segments or []
    if not segments:
        return ("", "", None, None)
    origin = segments[0].get("origin", "")
    destination = segments[-1].get("destination", "")
    depart_raw = segments[0].get("depart_at")
    departure = date.fromisoformat(depart_raw[:10]) if depart_raw else None
    return (origin, destination, departure, None)


def build_offer_links(
    offer: FlightOffer,
    airline: Airline | None = None,
    search: Search | None = None,
) -> list[BookingLink]:
    """Ordered booking options for a persisted offer."""
    links: list[BookingLink] = []

    if airline is not None and airline.direct_booking_url:
        note = "Booking direct gives the strongest schedule-change protection"
        if airline.loyalty_program:
            note += f" and {airline.loyalty_program} credit"
        links.append(BookingLink(
            kind="airline_direct",
            label=f"Book direct with {airline.name}",
            url=airline.direct_booking_url,
            note=note + ".",
        ))

    deep = offer.deep_link or offer.booking_url
    if deep:
        links.append(BookingLink(
            kind="source",
            label=f"Book this exact fare via {offer.source}",
            url=deep,
            note=f"The ${float(offer.price_usd):,.0f} price was quoted here; "
                 "re-verify before paying.",
        ))

    origin, destination, departure, ret = _offer_route(offer, search)
    if origin and destination and departure:
        links.append(BookingLink(
            kind="google_flights",
            label=f"Google Flights: {origin}→{destination}",
            url=google_flights_url(origin, destination, departure, ret),
            note="Cross-check the price and alternative itineraries.",
        ))

    return links
