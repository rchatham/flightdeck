"""Celery application + beat schedule.

Workers consume from Redis (broker) and write back to Redis (result backend).
The beat scheduler runs the daily price-history scraper at 02:00 local.

Run worker:  uv run celery -A app.workers.celery_app worker --loglevel=info
Run beat:    uv run celery -A app.workers.celery_app beat --loglevel=info
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "flightdeck",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=[
        "app.workers.price_history_scraper",
        "app.workers.watch_checker",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes hard cap per task
    beat_schedule={
        "scrape-popular-routes-daily": {
            "task": "app.workers.price_history_scraper.scrape_popular_routes",
            "schedule": crontab(minute=0, hour=2),  # 02:00 UTC daily
        },
        "check-price-watches": {
            "task": "app.workers.watch_checker.check_all_watches",
            # Every 6h, offset from the scraper so quota bursts don't overlap.
            "schedule": crontab(minute=30, hour="3,9,15,21"),
        },
    },
)
