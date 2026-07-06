# FlightDeck

Flight search, analysis, and price tracking system.

Backend MVP — FastAPI service driven via a Click+Rich CLI (`flightdeck`) and Claude Code skills.

## Quickstart

```bash
make setup        # uv sync
make up           # start postgres + redis
make migrate      # apply DB migrations
make seed         # seed airports + transfer partners
make dev          # run API server on :8001
make health       # in another terminal — verify all components
```

See `Makefile` for full command list.

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

## Ports

To avoid collisions with other local services, FlightDeck uses non-default ports:

| Service | Port | Notes |
| --- | --- | --- |
| API | 8001 | 8000 reserved by business-agent |
| Postgres | 5434 | 5432/5433 used by other projects |
| Redis | 6381 | 6379/6380 used by other projects |
