"""Tests for the Redis-backed get_or_set cache helper.

The redis client is mocked (unittest.mock) rather than run against a real
server — fakeredis isn't a project dependency and we don't want to add one
just for this.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.cache import get_or_set


def _mock_client(get_return: bytes | None = None):
    client = AsyncMock()
    client.get = AsyncMock(return_value=get_return)
    client.set = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_miss_calls_fetch_and_caches_result():
    client = _mock_client(get_return=None)
    fetch = AsyncMock(return_value={"price": 100})

    with patch("app.services.cache.redis_asyncio.from_url", return_value=client):
        result = await get_or_set("k", 300, fetch)

    assert result == {"price": 100}
    fetch.assert_awaited_once()
    client.set.assert_awaited_once()
    args, kwargs = client.set.call_args
    assert args[0] == "k"
    assert json.loads(args[1]) == {"price": 100}
    assert kwargs["ex"] == 300


@pytest.mark.asyncio
async def test_hit_returns_cached_value_without_calling_fetch():
    client = _mock_client(get_return=json.dumps({"price": 50}).encode())
    fetch = AsyncMock(return_value={"price": 999})

    with patch("app.services.cache.redis_asyncio.from_url", return_value=client):
        result = await get_or_set("k", 300, fetch)

    assert result == {"price": 50}
    fetch.assert_not_awaited()
    client.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_ttl_is_passed_through_to_set():
    client = _mock_client(get_return=None)
    fetch = AsyncMock(return_value=[1, 2, 3])

    with patch("app.services.cache.redis_asyncio.from_url", return_value=client):
        await get_or_set("k", 600, fetch)

    assert client.set.call_args.kwargs["ex"] == 600


@pytest.mark.asyncio
async def test_fail_open_on_get_error_still_returns_fetch_result():
    client = _mock_client()
    client.get = AsyncMock(side_effect=ConnectionError("redis down"))
    fetch = AsyncMock(return_value={"price": 42})

    with patch("app.services.cache.redis_asyncio.from_url", return_value=client):
        result = await get_or_set("k", 300, fetch)

    assert result == {"price": 42}
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_fail_open_on_connection_error_still_returns_fetch_result():
    fetch = AsyncMock(return_value={"price": 7})

    with patch(
        "app.services.cache.redis_asyncio.from_url", side_effect=ConnectionError("no redis")
    ):
        result = await get_or_set("k", 300, fetch)

    assert result == {"price": 7}
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_fail_open_on_set_error_still_returns_fetch_result():
    client = _mock_client(get_return=None)
    client.set = AsyncMock(side_effect=ConnectionError("redis down on write"))
    fetch = AsyncMock(return_value={"price": 13})

    with patch("app.services.cache.redis_asyncio.from_url", return_value=client):
        result = await get_or_set("k", 300, fetch)

    assert result == {"price": 13}
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_fail_open_on_corrupt_cached_json_falls_back_to_fetch():
    client = _mock_client(get_return=b"not-json{{{")
    fetch = AsyncMock(return_value={"price": 21})

    with patch("app.services.cache.redis_asyncio.from_url", return_value=client):
        result = await get_or_set("k", 300, fetch)

    assert result == {"price": 21}
    fetch.assert_awaited_once()
