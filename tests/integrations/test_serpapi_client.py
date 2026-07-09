"""HTTP-level tests for SerpApiClient: request shaping, auth param, and response parsing."""
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
import respx

from app.integrations.serpapi import SerpApiClient, SerpApiError

BASE_URL = "https://serpapi.com"

SEARCH_BODY = {
    "best_flights": [
        {
            "price": 892,
            "total_duration": 690,
            "booking_token": "tok_abc",
            "flights": [
                {
                    "departure_airport": {"id": "SFO", "time": "2026-06-15 11:00"},
                    "arrival_airport": {"id": "NRT", "time": "2026-06-16 15:30"},
                    "duration": 690,
                    "flight_number": "UA 837",
                    "travel_class": "Economy",
                }
            ],
        }
    ],
    "other_flights": [],
}


def make_client() -> SerpApiClient:
    return SerpApiClient(api_key="test-key")


@respx.mock
async def test_search_flight_offers_shapes_request_and_parses_response():
    route = respx.get(f"{BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )

    client = make_client()
    offers = await client.search_flight_offers(
        origin="sfo",
        destination="nrt",
        departure_date=date(2026, 6, 15),
        adults=1,
        cabin_class="business",
        max_results=20,
        non_stop=True,
    )
    await client.aclose()

    assert route.called
    request = route.calls[0].request
    query = dict(httpx.QueryParams(request.url.query.decode()))
    assert query["api_key"] == "test-key"
    assert query["engine"] == "google_flights"
    assert query["departure_id"] == "SFO"
    assert query["arrival_id"] == "NRT"
    assert query["outbound_date"] == "2026-06-15"
    assert query["currency"] == "USD"
    assert query["travel_class"] == "3"
    assert query["type"] == "2"
    assert query["stops"] == "1"
    assert "return_date" not in query

    assert len(offers) == 1
    offer = offers[0]
    assert offer.source == "serpapi"
    assert offer.source_id == "tok_abc"
    assert offer.price_usd == Decimal("892")
    assert offer.stops == 0
    assert offer.total_duration == timedelta(minutes=690)
    assert len(offer.segments) == 1
    seg = offer.segments[0]
    assert seg.carrier == "UA"
    assert seg.flight_no == "837"
    assert seg.cabin == "economy"


@respx.mock
async def test_search_flight_offers_round_trip_sets_type_and_return_date():
    route = respx.get(f"{BASE_URL}/search").mock(
        return_value=httpx.Response(200, json={"best_flights": [], "other_flights": []})
    )

    client = make_client()
    await client.search_flight_offers(
        origin="SFO",
        destination="NRT",
        departure_date=date(2026, 6, 15),
        return_date=date(2026, 6, 22),
    )
    await client.aclose()

    query = dict(httpx.QueryParams(route.calls[0].request.url.query.decode()))
    assert query["type"] == "1"
    assert query["return_date"] == "2026-06-22"


@respx.mock
async def test_combines_best_and_other_flights_and_respects_max_results():
    body = {
        "best_flights": [{**SEARCH_BODY["best_flights"][0], "booking_token": "a"}],
        "other_flights": [{**SEARCH_BODY["best_flights"][0], "booking_token": "b"}],
    }
    respx.get(f"{BASE_URL}/search").mock(return_value=httpx.Response(200, json=body))

    client = make_client()
    offers = await client.search_flight_offers(
        origin="SFO", destination="NRT", departure_date=date(2026, 6, 15), max_results=1
    )
    await client.aclose()

    assert len(offers) == 1
    assert offers[0].source_id == "a"


@respx.mock
async def test_server_error_raises_serpapi_error_not_raw_httpx_exception():
    respx.get(f"{BASE_URL}/search").mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )

    client = make_client()
    with pytest.raises(SerpApiError):
        await client.search_flight_offers("SFO", "NRT", date(2026, 6, 15))
    await client.aclose()


@respx.mock
async def test_unauthorized_raises_serpapi_error():
    respx.get(f"{BASE_URL}/search").mock(
        return_value=httpx.Response(401, json={"error": "Invalid API key"})
    )

    client = make_client()
    with pytest.raises(SerpApiError):
        await client.search_flight_offers("SFO", "NRT", date(2026, 6, 15))
    await client.aclose()


async def test_missing_api_key_raises_serpapi_error_without_network():
    client = SerpApiClient(api_key="")
    with pytest.raises(SerpApiError):
        await client.search_flight_offers("SFO", "NRT", date(2026, 6, 15))
    await client.aclose()
