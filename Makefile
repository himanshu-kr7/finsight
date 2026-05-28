# ============================================================================
# finsight — developer commands
#
# Run `make help` to see all available targets.
# ============================================================================

# Use bash for richer scripting (-e exits on error, -u catches undefined vars).
SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c

# Defaults
PYTHON := uv run python
PYTEST := uv run pytest
RUFF := uv run ruff
MYPY := uv run mypy
COMPOSE := docker compose
API_DIR := apps/api

# Make "help" the default target — `make` with no args shows the menu.
.DEFAULT_GOAL := help

# All targets are phony (not real files) — declare them so make doesn't get
# confused if a file with the same name ever exists.
.PHONY: help install dev down restart logs ps shell-api \
        build rebuild test test-cov lint format typecheck check \
        precommit-install precommit-run \
        api-local api-shell \
        clean clean-docker clean-all

# ----------------------------------------------------------------------------
# Help — auto-generated from `## comments after target names
# ----------------------------------------------------------------------------
help:  ## Show this help message
	@echo ""
	@echo "finsight — make targets"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""

# ----------------------------------------------------------------------------
# Setup
# ----------------------------------------------------------------------------
install:  ## Install all backend dependencies (creates apps/api/.venv)
	cd $(API_DIR) && uv sync --extra dev

precommit-install:  ## Install pre-commit hooks into .git/hooks
	cd $(API_DIR) && uv run pre-commit install
	cd $(API_DIR) && uv run pre-commit install --hook-type commit-msg

precommit-run:  ## Run all pre-commit hooks on all files
	cd $(API_DIR) && uv run pre-commit run --all-files

# ----------------------------------------------------------------------------
# Docker stack — full dev environment
# ----------------------------------------------------------------------------
dev:  ## Start the full stack in the background (api + qdrant + postgres + redis)
	$(COMPOSE) up -d
	@echo ""
	@echo "Stack starting. Tail logs with: make logs"
	@echo "Check status with:               make ps"
	@echo "API:           http://localhost:8000/docs"
	@echo "Qdrant UI:     http://localhost:6333/dashboard"

down:  ## Stop the stack (preserves volumes)
	$(COMPOSE) down

restart:  ## Restart the stack
	$(COMPOSE) restart

ps:  ## Show container status
	$(COMPOSE) ps

logs:  ## Tail logs from all services (Ctrl+C to exit)
	$(COMPOSE) logs -f --tail=100

logs-api:  ## Tail logs from the api service only
	$(COMPOSE) logs -f --tail=100 api

build:  ## Build the api docker image
	$(COMPOSE) build api

rebuild:  ## Force a clean rebuild of the api image (no cache)
	$(COMPOSE) build api --no-cache

shell-api:  ## Open a shell inside the running api container
	$(COMPOSE) exec api /bin/bash

# ----------------------------------------------------------------------------
# Local development (no Docker) — for fast iteration on the API
# ----------------------------------------------------------------------------
api-local:  ## Run the API locally with auto-reload on port 8000
	cd $(API_DIR) && uv run uvicorn finsight.api.main:app --reload --host 0.0.0.0 --port 8000

web-dev:  ## Run the Next.js dev server (Turbopack) on :3000
	pnpm --filter web dev
# ----------------------------------------------------------------------------
# Quality gates — what CI runs
# ----------------------------------------------------------------------------
lint:  ## Run ruff lint (no fixes)
	cd $(API_DIR) && $(RUFF) check src tests

format:  ## Auto-format and auto-fix lint issues
	cd $(API_DIR) && $(RUFF) check --fix src tests
	cd $(API_DIR) && $(RUFF) format src tests

typecheck:  ## Run mypy strict type-checking
	cd $(API_DIR) && $(MYPY) src

test:  ## Run all tests (with coverage)
	cd $(API_DIR) && $(PYTEST)

test-cov:  ## Run tests and open coverage HTML report
	cd $(API_DIR) && $(PYTEST)
	@echo "Coverage report: file://$(PWD)/$(API_DIR)/htmlcov/index.html"

check: lint typecheck test  ## Run lint + typecheck + test (full quality gate)
	@echo ""
	@echo "All checks passed."

# ----------------------------------------------------------------------------
# Cleanup
# ----------------------------------------------------------------------------
clean:  ## Remove Python build artifacts and caches
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .mypy_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
	find . -type d -name htmlcov -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete
	rm -rf $(API_DIR)/dist $(API_DIR)/build

clean-docker:  ## Stop the stack and delete its volumes (DATA LOSS)
	$(COMPOSE) down -v

clean-all: clean clean-docker  ## Full cleanup: caches + docker volumes
	@echo ""
	@echo "Full cleanup complete."
