import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api.routes.fares import router as fares_router
from app.api.routes.search import router as search_router
from app.api.routes.timing import router as timing_router
from app.api.routes.watches import router as watches_router
from app.config import get_settings
from app.db import get_engine

logger = logging.getLogger("flightdeck")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    logger.info("FlightDeck starting (env=%s, port=%s)", settings.env, settings.api_port)
    yield
    await get_engine().dispose()
    logger.info("FlightDeck shut down")


app = FastAPI(
    title="FlightDeck",
    description="Flight search, analysis, and price tracking system",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(search_router)
app.include_router(timing_router)
app.include_router(fares_router)
app.include_router(watches_router)


@app.get("/health")
async def health() -> dict:
    """Liveness probe — returns OK if the API process is up."""
    return {"status": "ok"}


@app.get("/health/db")
async def health_db() -> dict:
    """Readiness probe — verifies Postgres is reachable."""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        result.scalar_one()
    return {"status": "ok", "database": "reachable"}
