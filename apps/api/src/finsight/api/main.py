"""FastAPI application factory.

Creates the FastAPI app instance, configures middleware, mounts routes, and
manages the application lifecycle.

Usage:
    uvicorn finsight.api.main:app --reload --host 0.0.0.0 --port 8000

Or programmatically:
    from finsight.api.main import create_app
    app = create_app()
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from finsight.api.routes import health
from finsight.config import get_settings
from finsight.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler.

    Runs once on startup (before yield) and once on shutdown (after yield).
    All long-lived resources (database pools, vector store clients, ML models)
    should be initialized here and stashed on `app.state`.
    """
    settings = get_settings()
    configure_logging()

    log.info(
        "app_starting",
        env=settings.app.env.value,
        debug=settings.app.debug,
        log_level=settings.app.log_level.value,
    )

    # Placeholder — future phases will initialize resources here:
    #   app.state.qdrant = await create_qdrant_client(settings)
    #   app.state.db = await create_db_pool(settings)
    #   app.state.redis = await create_redis_client(settings)

    yield

    # Shutdown
    log.info("app_stopping")
    # Placeholder — future phases will clean up resources here:
    #   await app.state.qdrant.close()
    #   await app.state.db.close()


def create_app() -> FastAPI:
    """Build and return the FastAPI app instance.

    Factory pattern (vs a module-level `app = FastAPI(...)`) lets tests
    construct fresh app instances with overridden settings.
    """
    settings = get_settings()

    app = FastAPI(
        title="finsight",
        description="Agentic RAG over SEC filings and earnings calls",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS — allow the Next.js frontend to call this API
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount routes
    app.include_router(health.router, tags=["health"])

    return app


# Module-level app instance for `uvicorn finsight.api.main:app`
app = create_app()
