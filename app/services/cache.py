"""Generic Redis-backed cache helper.

A single `get_or_set` wraps the common pattern: check Redis, call the fetch
function on a miss, store the result, return it. Redis is a convenience layer
here (dev/personal scale) — any connection or command error is logged and
treated as a cache miss so a Redis outage never breaks a caller's happy path.

Callers own JSON-encodability of the value they pass to `get_or_set`; this
module does not know about domain types like NormalizedOffer.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis_asyncio

from app.config import get_settings

logger = logging.getLogger(__name__)


async def get_or_set(
    key: str,
    ttl_seconds: int,
    fetch: Callable[[], Awaitable[Any]],
) -> Any:
    """Return the cached value for `key`, or call `fetch` and cache its result.

    On any Redis error (connection refused, timeout, bad data, ...) this logs
    a warning and falls back to calling `fetch` directly, uncached.
    """
    client = None
    try:
        client = redis_asyncio.from_url(get_settings().redis_url)
        cached = await client.get(key)
        if cached is not None:
            return json.loads(cached)
    except Exception as e:  # noqa: BLE001
        logger.warning("Cache read failed for key %s, falling back to live fetch: %s", key, e)
        client = None

    value = await fetch()

    if client is not None:
        try:
            await client.set(key, json.dumps(value), ex=ttl_seconds)
        except Exception as e:  # noqa: BLE001
            logger.warning("Cache write failed for key %s: %s", key, e)

    if client is not None:
        try:
            await client.aclose()
        except Exception as e:  # noqa: BLE001
            logger.warning("Cache client close failed: %s", e)

    return value
