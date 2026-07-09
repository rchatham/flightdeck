"""HTTP-level tests for AmadeusClient: request shaping, auth, and response parsing."""
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
import respx

from app.integrations.amadeus import AmadeusClient, AmadeusError

BASE_URL = "https://test.api.amadeus.com"

TOKEN_BODY = {
    "access_token": "fake-token-123",
    "token_type": "Bearer",
    "expires_in": 1800,
}

OFFER_BODY = {
    "data": [
        {
            "id": "1",
            "price": {"currency": "USD", "grandTotal": "892.40", "total": "892.40"},
            "itineraries": [
                {
                    "duration": "PT11H30M",
                    "segments": [
                        {
                            "id": "1",
                            "departure": {"iataCode": "SFO", "at": "2026-06-15T11:00:00"},
                            "arrival": {"iataCode": "NRT", "at": "2026-06-16T15:30:00"},
                            "carrierCode": "UA",
                            "number": "837",
                            "duration": "PT11H30M",
                        },
                    ],
                }
            ],
            "travelerPricings": [
                {"fareDetailsBySegment": [{"segmentId": "1", "cabin": "ECONOMY"}]}
            ],
        }
    ]
}


def make_client() -> AmadeusClient:
    return AmadeusClient(
        api_key="test-key", api_secret="test-secret", base_url=BASE_URL
    )


@respx.mock
async def test_search_flight_offers_shapes_request_and_parses_response():
    token_route = respx.post(f"{BASE_URL}/v1/security/oauth2/token").mock(
        return_value=httpx.Response(200, json=TOKEN_BODY)
    )
    offers_route = respx.get(f"{BASE_URL}/v2/shopping/flight-offers").mock(
        return_value=httpx.Response(200, json=OFFER_BODY)
    )

    client = make_client()
    offers = await client.search_flight_offers(
        origin="sfo",
        destination="nrt",
        departure_date=date(2026, 6, 15),
        adults=2,
        cabin_class="business",
        max_results=5,
        non_stop=True,
    )
    await client.aclose()

    # --- token request shape ---
    assert token_route.called
    token_request = token_route.calls[0].request
    token_form = dict(httpx.QueryParams(token_request.content.decode()))
    assert token_form == {
        "grant_type": "client_credentials",
        "client_id": "test-key",
        "client_secret": "test-secret",
    }

    # --- offers request shape ---
    assert offers_route.called
    offers_request = offers_route.calls[0].request
    assert offers_request.headers["Authorization"] == "Bearer fake-token-123"
    query = dict(httpx.QueryParams(offers_request.url.query.decode()))
    assert query["originLocationCode"] == "SFO"
    assert query["destinationLocationCode"] == "NRT"
    assert query["departureDate"] == "2026-06-15"
    assert query["adults"] == "2"
    assert query["max"] == "5"
    assert query["currencyCode"] == "USD"
    assert query["travelClass"] == "BUSINESS"
    assert query["nonStop"] == "true"
    assert "returnDate" not in query

    # --- parsed response ---
    assert len(offers) == 1
    offer = offers[0]
    assert offer.source == "amadeus"
    assert offer.source_id == "1"
    assert offer.price_usd == Decimal("892.40")
    assert offer.currency == "USD"
    assert offer.total_duration == timedelta(hours=11, minutes=30)
    assert offer.stops == 0
    assert len(offer.segments) == 1
    seg = offer.segments[0]
    assert seg.carrier == "UA"
    assert seg.flight_no == "837"
    assert seg.origin == "SFO"
    assert seg.destination == "NRT"
    assert seg.cabin == "economy"


@respx.mock
async def test_search_flight_offers_includes_return_date_when_round_trip():
    respx.post(f"{BASE_URL}/v1/security/oauth2/token").mock(
        return_value=httpx.Response(200, json=TOKEN_BODY)
    )
    offers_route = respx.get(f"{BASE_URL}/v2/shopping/flight-offers").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    client = make_client()
    await client.search_flight_offers(
        origin="SFO",
        destination="NRT",
        departure_date=date(2026, 6, 15),
        return_date=date(2026, 6, 22),
    )
    await client.aclose()

    query = dict(httpx.QueryParams(offers_route.calls[0].request.url.query.decode()))
    assert query["returnDate"] == "2026-06-22"


@respx.mock
async def test_token_is_cached_across_multiple_searches():
    token_route = respx.post(f"{BASE_URL}/v1/security/oauth2/token").mock(
        return_value=httpx.Response(200, json=TOKEN_BODY)
    )
    respx.get(f"{BASE_URL}/v2/shopping/flight-offers").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    client = make_client()
    await client.search_flight_offers("SFO", "NRT", date(2026, 6, 15))
    await client.search_flight_offers("SFO", "NRT", date(2026, 6, 16))
    await client.aclose()

    assert token_route.call_count == 1


@respx.mock
async def test_auth_failure_raises_amadeus_error():
    respx.post(f"{BASE_URL}/v1/security/oauth2/token").mock(
        return_value=httpx.Response(401, text="invalid client credentials")
    )

    client = make_client()
    with pytest.raises(AmadeusError):
        await client.search_flight_offers("SFO", "NRT", date(2026, 6, 15))
    await client.aclose()


@respx.mock
async def test_server_error_raises_amadeus_error_not_raw_httpx_exception():
    respx.post(f"{BASE_URL}/v1/security/oauth2/token").mock(
        return_value=httpx.Response(200, json=TOKEN_BODY)
    )
    respx.get(f"{BASE_URL}/v2/shopping/flight-offers").mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )

    client = make_client()
    with pytest.raises(AmadeusError):
        await client.search_flight_offers("SFO", "NRT", date(2026, 6, 15))
    await client.aclose()


async def test_missing_credentials_raises_amadeus_error_without_network():
    client = AmadeusClient(api_key="", api_secret="", base_url=BASE_URL)
    with pytest.raises(AmadeusError):
        await client.search_flight_offers("SFO", "NRT", date(2026, 6, 15))
    await client.aclose()
