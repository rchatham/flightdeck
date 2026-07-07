# FlightDeck

Flight search, analysis, and price tracking system.

Backend MVP — FastAPI service driven via a Click+Rich CLI (`flightdeck`) and Claude Code skills.

## Quickstart

```bash
make setup        # uv sync
make up           # start postgres + redis
make migrate      # apply DB migrations
make seed         # seed airports + transfer partners
make dev          # run API server on :8002
make health       # in another terminal — verify all components
```

See `Makefile` for full command list.

## Web dashboard

`make dev`, then open <http://localhost:8002/> — a single-page dashboard
(served by the API itself, no separate frontend) for watches, alerts,
search + booking links, and timing analysis. The JSON API is documented at
<http://localhost:8002/docs>.

## Price watches

Track a specific trip and get alerted when the price is right:

```bash
flightdeck watch add SFO NRT 2026-10-15 --target 800   # alert at/below $800
flightdeck watch list
flightdeck watch check <WATCH_ID>                       # live check now
flightdeck watch alerts                                 # unacknowledged alerts
```

The Celery beat schedule checks all active watches every 6 hours. Alert
policy lives in `app/services/alert_rules.py` (Hook 4).

Fired alerts can push to your phone via [ntfy.sh](https://ntfy.sh) and/or a
generic JSON webhook — set `FLIGHTDECK_NTFY_TOPIC` or
`FLIGHTDECK_ALERT_WEBHOOK_URL` (see `.env.example`). Delivery is
best-effort; alerts always land in the database regardless.

## Booking handoff

FlightDeck doesn't issue tickets — it hands you the best places to buy,
ordered by protection quality (airline direct → exact fare deep link →
Google Flights price check):

```bash
flightdeck book <OFFER_ID>          # offer ids come from `flightdeck search`
flightdeck watch book <WATCH_ID>    # book a watched trip after an alert
```

## Ports

To avoid collisions with other local services, FlightDeck uses non-default ports:

| Service | Port | Notes |
| --- | --- | --- |
| API | 8002 | 8000 business-agent, 8001 hermes |
| Postgres | 5434 | 5432/5433 used by other projects |
| Redis | 6382 | 6379-6381 used by other projects |
