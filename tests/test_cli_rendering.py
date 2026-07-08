"""Smoke tests for CLI render functions — payload dict in, Rich output out.

These are the templates users actually read; a bad dict-key access or format
spec here is invisible to API/service tests but breaks the CLI outright.
Rich's Console resolves sys.stdout dynamically at write time, so pytest's
`capsys` captures it with no monkeypatching required.

Each test just checks the function doesn't raise and that a few expected
values made it into the rendered text — not a pixel-perfect layout check.
"""
from __future__ import annotations

from app.cli.commands.book import render_booking_links
from app.cli.commands.deals import _render_resolve, _render_scan
from app.cli.commands.fares import _render_opportunities
from app.cli.commands.health import _render_human
from app.cli.commands.points import _render_estimate, _render_list, _render_partners
from app.cli.commands.search import _render_results
from app.cli.commands.timing import _render_analyze, _render_history
from app.cli.commands.watch import _render_alerts, _render_check, _render_watch, _render_watch_list

# --- search ----------------------------------------------------------------------


def test_render_search_results_empty(capsys):
    _render_results({"origin": "SFO", "destination": "NRT", "departure_date": "2026-09-01",
                     "search_id": "x", "offers": []})
    assert "No offers found" in capsys.readouterr().out


def test_render_search_results_with_offers(capsys):
    _render_results({
        "origin": "SFO", "destination": "NRT", "departure_date": "2026-09-01",
        "search_id": "abc123",
        "offers": [{
            "id": "offer-uuid-1", "price_usd": "742.00", "stops": 1,
            "total_duration": "PT14H35M", "source": "kiwi",
            "segments": [{"origin": "SFO", "destination": "ICN", "carrier": "UA"},
                        {"origin": "ICN", "destination": "NRT", "carrier": "UA"}],
        }],
    })
    out = capsys.readouterr().out
    assert "$742.00" in out
    assert "SFO" in out and "NRT" in out


# --- deals -------------------------------------------------------------------------


def test_render_resolve_no_matches(capsys):
    _render_resolve({"query": "nowhereland", "kind": "name", "label": "nowhereland",
                     "airports": []})
    assert "No airports found" in capsys.readouterr().out


def test_render_resolve_with_matches(capsys):
    _render_resolve({
        "query": "tokyo", "kind": "name", "label": "Tokyo",
        "airports": [{"iata_code": "NRT", "name": "Narita Intl", "city": "Tokyo",
                      "country": "JP", "distance_km": 0.0}],
    })
    out = capsys.readouterr().out
    assert "Tokyo" in out and "NRT" in out


def test_render_scan_no_offers(capsys):
    _render_scan({
        "origin_label": "SF", "origin_airports": ["SFO"], "destination_label": "Tokyo",
        "destination_airports": ["NRT"], "date_from": "2026-09-01", "date_to": "2026-09-30",
        "searches_run": 4, "by_date": [], "best": None, "booking_links": [], "opportunities": [],
    })
    assert "No offers found" in capsys.readouterr().out


def test_render_scan_with_best_and_hacker_fare(capsys):
    _render_scan({
        "origin_label": "San Francisco", "origin_airports": ["SFO", "OAK"],
        "destination_label": "Tokyo", "destination_airports": ["NRT", "HND"],
        "date_from": "2026-09-01", "date_to": "2026-09-30", "searches_run": 12,
        "by_date": [{"departure_date": "2026-09-15", "origin": "OAK", "destination": "HND",
                    "price_usd": "715", "stops": 1, "source": "kiwi",
                    "vs_median_pct": -27.0, "tier": "DEAL"}],
        "best": {"departure_date": "2026-09-15", "return_date": None, "origin": "OAK",
                "destination": "HND", "price_usd": "715", "source": "kiwi", "stops": 1,
                "vs_median_pct": -27.0, "tier": "DEAL"},
        "booking_links": [{"kind": "google_flights", "label": "Google Flights",
                          "url": "https://x", "note": "check it"}],
        "opportunities": [{"strategy": "split_ticket", "price_usd": "640", "savings_usd": "75",
                          "savings_pct": 10.5, "risk_level": "LOW",
                          "risk_reasoning": "Same carrier.", "booking_steps": ["Book leg 1."]}],
    })
    out = capsys.readouterr().out
    assert "Best day to fly" in out
    assert "$715" in out
    assert "Hacker fare" in out


# --- fares -------------------------------------------------------------------------


def test_render_opportunities_empty(capsys):
    _render_opportunities({"origin": "SFO", "destination": "NRT", "departure_date": "2026-09-01",
                           "direct_price_usd": "900", "opportunity_count": 0, "opportunities": []})
    out = capsys.readouterr().out
    assert "No hidden-fare opportunities" in out


def test_render_opportunities_with_hidden_city(capsys):
    _render_opportunities({
        "origin": "SFO", "destination": "NRT", "departure_date": "2026-09-01",
        "direct_price_usd": "900", "opportunity_count": 1,
        "opportunities": [{
            "strategy": "hidden_city", "overall_risk": "HIGH", "savings_usd": "150",
            "savings_pct": 16.7, "price_usd": "750", "risk_reasoning": "Skiplagging risk.",
            "risk_flags": [{"code": "bag_loss", "severity": "HIGH", "description": "No bags."}],
            "booking_steps": ["Book one-way.", "Get off at NRT."],
            "real_destination": "NRT", "final_destination": "TPE",
        }],
    })
    out = capsys.readouterr().out
    assert "Save $150.00" in out
    assert "Get off at NRT" in out


# --- watch -------------------------------------------------------------------------


def _watch_payload(**overrides) -> dict:
    base = {"id": "watch-1", "origin": "SFO", "destination": "NRT", "departure_date": "2026-10-15",
           "return_date": None, "cabin_class": "economy", "target_price_usd": "800",
           "last_price_usd": None, "lowest_seen_usd": None, "active": True}
    base.update(overrides)
    return base


def test_render_watch(capsys):
    _render_watch(_watch_payload())
    out = capsys.readouterr().out
    assert "SFO" in out and "NRT" in out and "800" in out


def test_render_watch_list_empty(capsys):
    _render_watch_list({"count": 0, "watches": []})
    assert "No watches yet" in capsys.readouterr().out


def test_render_watch_list_with_watches(capsys):
    _render_watch_list({"count": 1, "watches": [{
        "id": "watch-1", "origin": "SFO", "destination": "NRT", "departure_date": "2026-10-15",
        "target_price_usd": "800", "last_price_usd": "750", "lowest_seen_usd": "720",
        "last_checked_at": "2026-07-01T12:00:00",
    }]})
    out = capsys.readouterr().out
    assert "SFO" in out and "$750" in out


def test_render_alerts_empty(capsys):
    _render_alerts({"count": 0, "alerts": []})
    assert "No unacknowledged alerts" in capsys.readouterr().out


def test_render_alerts_with_alert(capsys):
    _render_alerts({"count": 1, "alerts": [{
        "id": "alert-1", "kind": "target_hit", "price_usd": "750", "previous_price_usd": "900",
        "message": "Price hit your target.", "acknowledged": False,
        "created_at": "2026-07-01T12:00:00",
    }]})
    out = capsys.readouterr().out
    assert "TARGET_HIT" in out
    assert "Price hit your target." in out


def test_render_check_deactivated(capsys):
    _render_check({"deactivated": True})
    assert "deactivated" in capsys.readouterr().out.lower()


def test_render_check_alert_fired(capsys):
    _render_check({
        "deactivated": False, "offers_found": 3, "cheapest_price_usd": "715",
        "alert_fired": True,
        "alert": {"id": "alert-1", "kind": "new_low", "price_usd": "715",
                 "previous_price_usd": "800", "message": "New low!", "acknowledged": False,
                 "created_at": "2026-07-01T12:00:00"},
        "watch": _watch_payload(last_price_usd="715"),
    })
    out = capsys.readouterr().out
    assert "3" in out and "New low!" in out


# --- timing ------------------------------------------------------------------------


def test_render_analyze(capsys):
    _render_analyze({
        "route": "SFO-NRT", "departure_date": "2026-10-15", "days_until_departure": 100,
        "verdict": "WAIT", "confidence": 0.72, "reasoning": "Prices trend down closer in.",
        "median_price": "820.00", "current_pct_above_median": 12.5, "sample_count": 42,
    })
    out = capsys.readouterr().out
    assert "WAIT" in out and "72%" in out


def test_render_history_empty(capsys):
    _render_history({"route_key": "SFO-NRT", "point_count": 0, "points": []})
    assert "No history yet" in capsys.readouterr().out


def test_render_history_with_points(capsys):
    _render_history({"route_key": "SFO-NRT", "point_count": 1, "points": [
        {"recorded_at": "2026-07-01T12:00:00", "price_usd": "800.00", "days_until_departure": 90},
    ]})
    out = capsys.readouterr().out
    assert "SFO-NRT" in out and "800.00" in out


# --- book ------------------------------------------------------------------------


def test_render_booking_links_empty(capsys):
    render_booking_links({"context": "SFO -> NRT", "links": []})
    assert "No booking links available" in capsys.readouterr().out


def test_render_booking_links_with_links(capsys):
    render_booking_links({"context": "SFO -> NRT", "links": [
        {"kind": "airline_direct", "label": "Book direct with ANA",
         "url": "https://ana.co.jp", "note": "Best protection."},
    ]})
    out = capsys.readouterr().out
    assert "BEST PROTECTION" in out and "ana.co.jp" in out


# --- health ------------------------------------------------------------------------


def test_render_health(capsys):
    _render_human({
        "api": {"status": "ok", "detail": "http://localhost:8002"},
        "postgres": {"status": "ok", "detail": "localhost:5434/flightdeck"},
        "redis": {"status": "error", "detail": "connection refused"},
        "api_keys": [{"name": "Amadeus key", "status": "missing", "detail": "not set"}],
    })
    out = capsys.readouterr().out
    assert "ok" in out and "error" in out and "Amadeus key" in out


# --- points ------------------------------------------------------------------------


def test_render_points_list_empty(capsys):
    _render_list({"count": 0, "programs": []})
    assert "No points programs" in capsys.readouterr().out


def test_render_points_list_with_programs(capsys):
    _render_list({"count": 1, "programs": [{
        "program_name": "Chase Ultimate Rewards", "card_name": "Sapphire Preferred",
        "balance": 85000, "transfer_partners": [{"airline": "UA"}] * 11,
    }]})
    out = capsys.readouterr().out
    assert "Chase Ultimate Rewards" in out and "85,000" in out


def test_render_points_partners(capsys):
    _render_partners({
        "program_name": "Chase Ultimate Rewards", "card_name": "Sapphire Preferred",
        "balance": 85000,
        "transfer_partners": [{"airline": "United MileagePlus", "iata": "UA",
                              "ratio": "1:1", "bonus_pct": 0}],
    })
    out = capsys.readouterr().out
    assert "United MileagePlus" in out


def test_render_points_estimate(capsys):
    _render_estimate({
        "cash_price_usd": "750", "estimates": [
            {"program_name": "Chase Ultimate Rewards", "cents_per_point": 2.0,
             "points_needed": 37500, "balance": 85000, "sufficient": True, "shortfall": None},
            {"program_name": "Citi ThankYou Rewards", "cents_per_point": 1.7,
             "points_needed": 44118, "balance": 0, "sufficient": False, "shortfall": 44118},
        ],
    })
    out = capsys.readouterr().out
    assert "enough" in out and "short 44,118" in out
