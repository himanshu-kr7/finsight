"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finsight.api.main import create_app
from finsight.config import get_settings


@pytest.fixture(scope="session")
def app() -> Iterator[FastAPI]:
    """Build a FastAPI app for tests. Session-scoped — built once per run."""
    # Clear the settings cache so any env-var changes in tests are picked up.
    get_settings.cache_clear()
    yield create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Async HTTP client wired directly to the FastAPI app (no network)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
