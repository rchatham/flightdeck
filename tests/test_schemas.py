"""Validation tests for request/response Pydantic schemas.

Pure and hermetic — no DB, no network. Schemas are the API's outermost
contract; a validator that's too loose (or silently wrong, like the
date-ordering bug this file guards against) reaches every route built on it.
"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.api.schemas.deals import DealScanRequest
from app.api.schemas.fares import HiddenFareRequest
from app.api.schemas.points import BalanceUpdate, RedemptionEstimateRequest
from app.api.schemas.search import SearchRequest
from app.api.schemas.watches import WatchCreate

# --- SearchRequest -------------------------------------------------------------


def test_search_request_lowercases_are_normalized_to_upper():
    req = SearchRequest(origin="sfo", destination="nrt", departure_date=date(2026, 9, 1))
    assert req.origin == "SFO"
    assert req.destination == "NRT"


@pytest.mark.parametrize("field,value", [("origin", "SF"), ("origin", "SFOX"),
                                         ("destination", "NR"), ("destination", "NRTX")])
def test_search_request_rejects_wrong_length_iata(field, value):
    kwargs = {"origin": "SFO", "destination": "NRT", "departure_date": date(2026, 9, 1)}
    kwargs[field] = value
    with pytest.raises(ValidationError):
        SearchRequest(**kwargs)


@pytest.mark.parametrize("flex_days", [-1, 8])
def test_search_request_rejects_flex_days_out_of_bounds(flex_days):
    with pytest.raises(ValidationError):
        SearchRequest(origin="SFO", destination="NRT", departure_date=date(2026, 9, 1),
                      flex_days=flex_days)


@pytest.mark.parametrize("passengers", [0, 10])
def test_search_request_rejects_passengers_out_of_bounds(passengers):
    with pytest.raises(ValidationError):
        SearchRequest(origin="SFO", destination="NRT", departure_date=date(2026, 9, 1),
                      passengers=passengers)


def test_search_request_rejects_invalid_cabin_class():
    with pytest.raises(ValidationError):
        SearchRequest(origin="SFO", destination="NRT", departure_date=date(2026, 9, 1),
                      cabin_class="business_x")


def test_search_request_rejects_max_stops_out_of_bounds():
    with pytest.raises(ValidationError):
        SearchRequest(origin="SFO", destination="NRT", departure_date=date(2026, 9, 1),
                      max_stops=4)


def test_search_request_return_origin_destination_normalized_to_upper():
    req = SearchRequest(origin="sfo", destination="nrt", departure_date=date(2026, 9, 1),
                        return_date=date(2026, 9, 10), return_origin="hnd",
                        return_destination="lax")
    assert req.return_origin == "HND"
    assert req.return_destination == "LAX"


def test_search_request_is_open_jaw_false_for_plain_round_trip():
    req = SearchRequest(origin="SFO", destination="NRT", departure_date=date(2026, 9, 1),
                        return_date=date(2026, 9, 10))
    assert req.is_open_jaw is False


def test_search_request_is_open_jaw_false_without_a_return_date():
    # Setting return_origin with no return_date isn't a real trip — no return leg to fly.
    req = SearchRequest(origin="SFO", destination="NRT", departure_date=date(2026, 9, 1),
                        return_origin="HND")
    assert req.is_open_jaw is False


@pytest.mark.parametrize("kwargs", [
    {"return_origin": "HND"},
    {"return_destination": "LAX"},
    {"return_origin": "HND", "return_destination": "LAX"},
])
def test_search_request_is_open_jaw_true_when_return_leg_differs(kwargs):
    req = SearchRequest(origin="SFO", destination="NRT", departure_date=date(2026, 9, 1),
                        return_date=date(2026, 9, 10), **kwargs)
    assert req.is_open_jaw is True


# --- WatchCreate -----------------------------------------------------------------


def test_watch_create_lowercases_are_normalized_to_upper():
    w = WatchCreate(origin="sfo", destination="nrt", departure_date=date(2026, 10, 15))
    assert w.origin == "SFO" and w.destination == "NRT"


def test_watch_create_target_price_none_allowed():
    w = WatchCreate(origin="SFO", destination="NRT", departure_date=date(2026, 10, 15))
    assert w.target_price_usd is None


def test_watch_create_rejects_negative_target_price():
    with pytest.raises(ValidationError):
        WatchCreate(origin="SFO", destination="NRT", departure_date=date(2026, 10, 15),
                   target_price_usd=-1)


# --- HiddenFareRequest -------------------------------------------------------------


def test_hidden_fare_request_rejects_wrong_length_iata():
    with pytest.raises(ValidationError):
        HiddenFareRequest(origin="SF", destination="NRT", departure_date=date(2026, 9, 1))


@pytest.mark.parametrize("passengers", [0, 10])
def test_hidden_fare_request_rejects_passengers_out_of_bounds(passengers):
    with pytest.raises(ValidationError):
        HiddenFareRequest(origin="SFO", destination="NRT", departure_date=date(2026, 9, 1),
                          passengers=passengers)


# --- DealScanRequest ---------------------------------------------------------------


def test_deal_scan_request_accepts_ordered_dates():
    req = DealScanRequest(origin="SFO", destination="NRT",
                          date_from=date(2026, 9, 1), date_to=date(2026, 9, 10))
    assert req.date_from < req.date_to


def test_deal_scan_request_accepts_equal_dates():
    req = DealScanRequest(origin="SFO", destination="NRT",
                          date_from=date(2026, 9, 1), date_to=date(2026, 9, 1))
    assert req.date_from == req.date_to


def test_deal_scan_request_rejects_backwards_date_range():
    with pytest.raises(ValidationError, match="date_to must be on or after date_from"):
        DealScanRequest(origin="SFO", destination="NRT",
                        date_from=date(2026, 9, 10), date_to=date(2026, 9, 1))


@pytest.mark.parametrize("max_searches", [0, 41])
def test_deal_scan_request_rejects_max_searches_out_of_bounds(max_searches):
    with pytest.raises(ValidationError):
        DealScanRequest(origin="SFO", destination="NRT",
                        date_from=date(2026, 9, 1), date_to=date(2026, 9, 10),
                        max_searches=max_searches)


@pytest.mark.parametrize("trip_length_days", [0, 91])
def test_deal_scan_request_rejects_trip_length_out_of_bounds(trip_length_days):
    with pytest.raises(ValidationError):
        DealScanRequest(origin="SFO", destination="NRT",
                        date_from=date(2026, 9, 1), date_to=date(2026, 9, 10),
                        trip_length_days=trip_length_days)


def test_deal_scan_request_allows_city_names_unlike_search_request():
    # Unlike SearchRequest, DealScanRequest deliberately allows non-IATA
    # queries (city names, "lat,lon") — no length/uppercase constraint.
    req = DealScanRequest(origin="san francisco", destination="37.77,-122.42",
                          date_from=date(2026, 9, 1), date_to=date(2026, 9, 10))
    assert req.origin == "san francisco"


# --- Points schemas ----------------------------------------------------------------


def test_balance_update_accepts_zero():
    assert BalanceUpdate(balance=0).balance == 0


def test_balance_update_rejects_negative():
    with pytest.raises(ValidationError):
        BalanceUpdate(balance=-1)


def test_redemption_estimate_request_accepts_zero():
    assert RedemptionEstimateRequest(cash_price_usd=0).cash_price_usd == 0


def test_redemption_estimate_request_rejects_negative():
    with pytest.raises(ValidationError):
        RedemptionEstimateRequest(cash_price_usd=-1)
