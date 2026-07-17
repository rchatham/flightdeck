"""Pure tests for route_optimizer's open-jaw leg-splitting.

No providers/DB/Redis involved — _open_jaw_leg_requests is a pure function.
"""
from __future__ import annotations

from datetime import date

from app.api.schemas.search import SearchRequest
from app.services.route_optimizer import _open_jaw_leg_requests


def _req(**overrides) -> SearchRequest:
    base = dict(origin="SFO", destination="NRT", departure_date=date(2027, 3, 1),
                return_date=date(2027, 3, 10))
    base.update(overrides)
    return SearchRequest(**base)


def test_outbound_leg_is_origin_to_destination_one_way():
    req = _req(return_origin="HND", return_destination="LAX")
    outbound, _ = _open_jaw_leg_requests(req)
    assert outbound.origin == "SFO"
    assert outbound.destination == "NRT"
    assert outbound.departure_date == date(2027, 3, 1)
    assert outbound.return_date is None
    assert outbound.return_origin is None
    assert outbound.return_destination is None


def test_return_leg_uses_explicit_return_origin_and_destination():
    req = _req(return_origin="HND", return_destination="LAX")
    _, return_leg = _open_jaw_leg_requests(req)
    assert return_leg.origin == "HND"
    assert return_leg.destination == "LAX"
    assert return_leg.departure_date == date(2027, 3, 10)
    assert return_leg.return_date is None


def test_return_leg_defaults_missing_side_to_the_outbound_pair():
    # Only return_origin set — return_destination defaults to the original origin.
    req = _req(return_origin="HND")
    _, return_leg = _open_jaw_leg_requests(req)
    assert return_leg.origin == "HND"
    assert return_leg.destination == "SFO"

    # Only return_destination set — return_origin defaults to the outbound destination.
    req2 = _req(return_destination="LAX")
    _, return_leg2 = _open_jaw_leg_requests(req2)
    assert return_leg2.origin == "NRT"
    assert return_leg2.destination == "LAX"
