# syntax=docker/dockerfile:1.7
# ============================================================================
# finsight API — multi-stage Docker build
#
# Stage 1 (builder): install uv, sync dependencies into a venv
# Stage 2 (runtime): copy the venv + source into a slim image, run as non-root
#
# The split keeps the final image small (no build tools, no uv) and secure
# (non-root user, no shell-as-default).
# ============================================================================

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.5.11


# ---------------------------------------------------------------------------
# Stage 1: builder
# Pulls Astral's prebuilt uv image, syncs deps into /app/.venv
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:${UV_VERSION}-python${PYTHON_VERSION}-bookworm-slim AS builder

# Faster, more reproducible installs:
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Copy only dependency manifests first so Docker layer caching works:
# this layer is invalidated only when these files change, not on every code edit.
COPY pyproject.toml uv.lock ./

# Install dependencies (without the project itself — we copy source after).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now copy source and install the project as an editable package.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# ---------------------------------------------------------------------------
# Stage 2: runtime
# Minimal Python image. Only the venv and source are copied over.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

# System packages required at runtime (curl for healthchecks, ca-certs for HTTPS).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user (security best practice; never run prod containers as root).
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --no-create-home app

WORKDIR /app

# Copy the venv and source from the builder.
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

# Make the venv's binaries available on PATH.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

EXPOSE 8000

# Container-level healthcheck — docker / kubernetes / cloud runners use this
# to know if the service is alive without needing an external prober.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health/live || exit 1

# Use uvicorn directly (not via uv) — smaller process tree, faster startup.
CMD ["uvicorn", "finsight.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
