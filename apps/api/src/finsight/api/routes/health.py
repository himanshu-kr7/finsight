"""Health check endpoints.

Three endpoints, each with a distinct purpose:
  - /health/live   : process is running (cheap, no dependencies)
  - /health/ready  : process can serve traffic (checks dependencies)
  - /health        : convenience alias for /health/live

Kubernetes/orchestration conventions:
  - liveness probes hit /health/live  (kill the pod if this fails)
  - readiness probes hit /health/ready (stop routing traffic if this fails)
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from finsight.config import get_settings

router = APIRouter(prefix="/health")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class LivenessResponse(BaseModel):
    """Response for liveness probe."""

    status: str = Field(default="alive", description="Always 'alive' if the endpoint responds.")
    service: str = Field(description="Service name.")
    version: str = Field(description="Service version.")
    timestamp: datetime = Field(description="Server time in UTC.")


class ReadinessResponse(BaseModel):
    """Response for readiness probe."""

    status: str = Field(description="'ready' or 'not_ready'.")
    service: str
    version: str
    timestamp: datetime
    checks: dict[str, str] = Field(
        default_factory=dict,
        description="Per-dependency status (e.g. {'qdrant': 'ok', 'postgres': 'ok'}).",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe (alias)",
)
@router.get(
    "/live",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
)
async def liveness() -> LivenessResponse:
    """Return 200 if the process is up. No dependency checks."""
    settings = get_settings()
    return LivenessResponse(
        service=settings.app.name,
        version="0.1.0",
        timestamp=datetime.now(UTC),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
)
async def readiness() -> ReadinessResponse:
    """Return 200 if the service can serve traffic.

    Future phases will check Qdrant, Postgres, Redis connectivity here and
    return 503 if any critical dependency is unreachable.
    """
    settings = get_settings()
    # Phase 1: no real dependencies yet, so we trivially report ready.
    # Phase 4 will populate `checks` with actual probes.
    return ReadinessResponse(
        status="ready",
        service=settings.app.name,
        version="0.1.0",
        timestamp=datetime.now(UTC),
        checks={},
    )
