"""Shared fixtures for route-level integration tests.

These hit the real dev Postgres (there's no separate test database) but wrap
every test in a SAVEPOINT that's rolled back afterward, so route handlers can
freely call `session.commit()` — as they do in normal operation — without any
of it surviving past the test. See SQLAlchemy's "Joining a Session into an
External Transaction" pattern.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import get_session
from app.main import app


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    # A fresh engine per test, not the app-wide cached one from app.db.get_engine() —
    # pytest-asyncio gives each test function its own event loop, and asyncpg
    # connections/pools are bound to the loop that created them. Reusing the
    # global singleton across tests intermittently breaks on pool_pre_ping.
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=False)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            factory = async_sessionmaker(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            async with factory() as session:
                yield session
            await trans.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)
