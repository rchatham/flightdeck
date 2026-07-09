"""HTTP-level tests for KiwiClient: request shaping, auth header, and response parsing."""
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
import respx

from app.integrations.kiwi import KiwiClient, KiwiError

BASE_URL = "https://api.tequila.kiwi.com"

SEARCH_BODY = {
    "data": [
        {
            "id": "abc123",
            "price": 612.50,
            "deep_link": "https://www.kiwi.com/booking?token=...",
            "virtual_interlining": False,
            "route": [
                {
                    "airline": "OZ",
                    "flight_no": 201,
                    "flyFrom": "SFO",
                    "flyTo": "ICN",
                    "local_departure": "2026-06-15T08:00:00.000Z",
                    "local_arrival": "2026-06-16T13:00:00.000Z",
                },
                {
                    "airline": "OZ",
                    "flight_no": 104,
                    "flyFrom": "ICN",
                    "flyTo": "NRT",
                    "local_departure": "2026-06-16T15:00:00.000Z",
                    "local_arrival": "2026-06-16T17:10:00.000Z",
                },
            ],
        }
    ]
}


def make_client() -> KiwiClient:
    return KiwiClient(api_key="test-key")


@respx.mock
async def test_search_flight_offers_shapes_request_and_parses_response():
    route = respx.get(f"{BASE_URL}/v2/search").mock(
        return_value=httpx.Response(200, json=SEARCH_BODY)
    )

    client = make_client()
    offers = await client.search_flight_offers(
        origin="sfo",
        destination="nrt",
        departure_date=date(2026, 6, 15),
        adults=1,
        cabin_class="economy",
        max_results=20,
        non_stop=True,
    )
    await client.aclose()

    assert route.called
    request = route.calls[0].request
    assert request.headers["apikey"] == "test-key"
    query = dict(httpx.QueryParams(request.url.query.decode()))
    assert query["fly_from"] == "SFO"
    assert query["fly_to"] == "NRT"
    assert query["date_from"] == "15/06/2026"
    assert query["date_to"] == "15/06/2026"
    assert query["selected_cabins"] == "M"
    assert query["curr"] == "USD"
    assert query["max_stopovers"] == "0"
    assert query["enable_vi"] == "false"

    assert len(offers) == 1
    offer = offers[0]
    assert offer.source == "kiwi"
    assert offer.source_id == "abc123"
    assert offer.price_usd == Decimal("612.50")
    assert offer.stops == 1
    assert offer.fare_type == "regular"
    assert offer.deep_link == "https://www.kiwi.com/booking?token=..."
    assert len(offer.segments) == 2
    assert offer.segments[0].origin == "SFO"
    assert offer.segments[1].destination == "NRT"
    assert offer.total_duration == timedelta(
        seconds=(
            (
                offer.segments[0].duration + offer.segments[1].duration
            ).total_seconds()
        )
    )


@respx.mock
async def test_search_flight_offers_includes_return_dates_when_round_trip():
    route = respx.get(f"{BASE_URL}/v2/search").mock(
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

    query = dict(httpx.QueryParams(route.calls[0].request.url.query.decode()))
    assert query["return_from"] == "22/06/2026"
    assert query["return_to"] == "22/06/2026"


@respx.mock
async def test_virtually_interlined_enables_vi_flag():
    route = respx.get(f"{BASE_URL}/v2/search").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    client = make_client()
    await client.search_flight_offers(
        origin="SFO",
        destination="NRT",
        departure_date=date(2026, 6, 15),
        virtually_interlined=True,
    )
    await client.aclose()

    query = dict(httpx.QueryParams(route.calls[0].request.url.query.decode()))
    assert "enable_vi" not in query


@respx.mock
async def test_server_error_raises_kiwi_error_not_raw_httpx_exception():
    respx.get(f"{BASE_URL}/v2/search").mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )

    client = make_client()
    with pytest.raises(KiwiError):
        await client.search_flight_offers("SFO", "NRT", date(2026, 6, 15))
    await client.aclose()


@respx.mock
async def test_unauthorized_raises_kiwi_error():
    respx.get(f"{BASE_URL}/v2/search").mock(
        return_value=httpx.Response(401, json={"error": "bad api key"})
    )

    client = make_client()
    with pytest.raises(KiwiError):
        await client.search_flight_offers("SFO", "NRT", date(2026, 6, 15))
    await client.aclose()


async def test_missing_api_key_raises_kiwi_error_without_network():
    client = KiwiClient(api_key="")
    with pytest.raises(KiwiError):
        await client.search_flight_offers("SFO", "NRT", date(2026, 6, 15))
    await client.aclose()
