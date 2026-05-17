# ADR 0001 — Initial architecture decisions

- **Status:** Accepted
- **Date:** 2026-05-17
- **Deciders:** Himanshu Kumar
- **Phase:** 1 (Foundation)

---

## Context

`finsight` is a portfolio-grade RAG system for financial-document analysis. Phase 1 establishes the foundation — repository structure, language stack, tooling, and deployment model — that all subsequent phases will build on. The decisions captured here have multi-month consequences, so they're worth documenting up front.

The driving constraints:

1. **Production-grade signal.** This is a portfolio project for AI/ML engineering roles. Choices should reflect what a senior engineer would do at a real company, not tutorial defaults.
2. **Modern but stable.** Prefer tools that represent where the ecosystem is heading (uv, ruff, Pydantic v2, FastAPI), but avoid alpha-stage libraries that may break mid-project.
3. **Phased delivery.** The project will evolve over six phases. The foundation must support frontend, agentic orchestration, ingestion pipelines, evaluation harnesses, and production observability — without rework.
4. **Solo developer.** No team coordination overhead. Decisions optimize for clarity and momentum, not for multi-contributor governance.

---

## Decision 1 — Monorepo with `apps/api` + `apps/web`

**Chosen:** A single git repository containing both the Python backend (`apps/api`) and the planned Next.js frontend (`apps/web`), with `pnpm-workspace.yaml` for JS workspace management.

**Alternatives considered:**

- **Separate `finsight-api` and `finsight-web` repos.** Cleaner per-service ownership, easier per-service versioning. But coordination overhead for cross-cutting changes (API contract updates, shared schemas) is significant, and the project is solo-developed. Rejected.
- **Single repo, flat structure (everything at root).** Common for small projects. But mixing Python and JS at root creates dependency-file collisions (`package.json` vs `pyproject.toml` at peer level) and makes per-language tooling harder. Rejected.

**Consequences:**

- **+** All cross-cutting changes are atomic. Adding a new API endpoint and the frontend code that calls it lands in one PR.
- **+** Shared resources (`docker-compose.yml`, `.env`, CI workflows, ADRs, docs) live at root with one source of truth.
- **+** Easy to add `apps/worker` or `apps/cli` later without restructuring.
- **−** Single git history mixes backend and frontend commits. Mitigated by conventional-commits scoping (`feat(api):` vs `feat(web):`) and per-path CI triggers.

---

## Decision 2 — Python 3.12 with `uv` as the package manager

**Chosen:** Python 3.12, dependency management via [uv](https://docs.astral.sh/uv/).

**Alternatives considered:**

- **`pip` + `requirements.txt`.** Universally supported but slow, no lockfile by default, no Python-version management, no project isolation. Rejected as below standard.
- **Poetry.** Mature, widely used, good lockfile semantics. But significantly slower than uv on every operation (install, resolve, lock), and its dependency resolver has periodic issues with packages like PyTorch and CUDA-bound libraries that will matter in later phases. Rejected.
- **Conda / Mamba.** Strong for scientific Python with native dependencies, but heavier and slower for a web service, and uv now covers the same ground for pure-Python workloads.

**Consequences:**

- **+** `uv sync` is 10–100x faster than Poetry's equivalent.
- **+** `uv.lock` produces deterministic builds across local dev, CI, and Docker.
- **+** Built-in Python version management — `uv python install 3.12` works on any machine.
- **+** Native PEP 723 script support, useful for one-off scripts in `scripts/` later.
- **−** uv is newer (first 1.0 release in 2024) than pip or Poetry, so some integrations are still maturing. Mitigated by using uv only for dependency management, not as the runtime — `uvicorn` and `pytest` are invoked directly inside Docker.

---

## Decision 3 — `src/` layout for the Python package

**Chosen:** Python source code lives in `apps/api/src/finsight/`, not `apps/api/finsight/`.

**Alternatives considered:**

- **Flat layout (`apps/api/finsight/`).** Simpler, fewer directory levels.

**Consequences:**

- **+** Tests cannot accidentally import from the working directory; they must import from the installed package. This catches packaging bugs (missing files, broken imports) before they ship.
- **+** Cleaner separation between source code and project metadata.
- **+** Standard recommendation by the Python Packaging Authority and adopted by major projects (FastAPI itself, Pydantic, httpx, etc.).
- **−** Slightly less intuitive for newcomers. Mitigated by being the modern standard — any senior Python developer will recognize it immediately.

---

## Decision 4 — FastAPI for the backend, Pydantic Settings for config

**Chosen:** FastAPI + Uvicorn for the HTTP layer; Pydantic Settings v2 for configuration.

**Alternatives considered:**

- **Flask.** Mature and ubiquitous, but synchronous-by-default. RAG systems are I/O-bound on LLM calls; async is essential. Rejected.
- **Django.** Excellent for traditional CRUD, but heavyweight for a service whose primary role is orchestrating LLM and vector-DB calls. Rejected.
- **Litestar.** Modern, async-native, very capable. Smaller ecosystem and less recruiter-recognition than FastAPI. Deferred — FastAPI is the safer choice for portfolio visibility.

For configuration:

- **`os.environ` direct reads.** Untyped, no validation, no autocompletion. Rejected.
- **`python-decouple` / `dynaconf`.** Reasonable, but Pydantic Settings integrates natively with Pydantic types we use elsewhere.

**Consequences:**

- **+** Async-native means we can call LLMs and vector DBs concurrently without ceremony.
- **+** Automatic OpenAPI/Swagger documentation at `/docs` and `/redoc` from type annotations.
- **+** Pydantic Settings validates configuration *at boot*, not at first use. Missing env vars fail fast with a clear error.
- **+** Type-safe access to config (`settings.qdrant.url` is a typed attribute, not a string lookup).
- **−** Slight learning curve for newcomers around async semantics. Acceptable trade.

---

## Decision 5 — Docker Compose for the local stack, with shifted host ports

**Chosen:** Full local stack runs via `docker compose up`, with each project shifting host ports by +1 from defaults (Postgres `5433:5432`, Redis `6380:6379`) to allow multiple projects to coexist.

**Alternatives considered:**

- **Bare-metal installs on the dev machine.** Faster iteration for the backend, but creates "works on my machine" problems and conflicts when running multiple projects simultaneously. Rejected as the *default* workflow, but kept available via `make api-local` for fast iteration during pure-API work.
- **Devcontainers / GitHub Codespaces.** Elegant but adds a layer of complexity for solo development, and most reviewers will not run the project — they'll read the code. Deferred.

**Consequences:**

- **+** Three commands (`git clone`, `cp .env.example .env`, `make dev`) bring up a fully-functional stack.
- **+** Port-shifting means multiple projects can run side-by-side on the same machine without manual juggling.
- **+** CI reuses the same Dockerfile, eliminating environment drift between local and CI builds.
- **−** Docker layer caching is occasionally finicky (we hit this in Phase 1 with `--no-cache` rebuilds). Acceptable.

---

## Decision 6 — Strict type-checking and linting as quality gates

**Chosen:** `ruff` for linting and formatting, `mypy --strict` for type-checking, `pytest` with branch coverage, all enforced via pre-commit hooks and GitHub Actions CI.

**Alternatives considered:**

- **black + isort + flake8.** The legacy stack. Ruff subsumes all three with a single tool that's 10–100x faster. Rejected as obsolete.
- **mypy in non-strict mode.** Easier to adopt incrementally. But for a greenfield project, strict mode catches more bugs and demonstrates higher engineering standards. Chosen for strict.
- **Skip type-checking entirely.** Common in research code. But this is production-aspiring code, and untyped Python rots quickly as the codebase grows. Rejected.

**Consequences:**

- **+** `make check` runs lint + typecheck + test as a single quality gate. The same command runs in CI.
- **+** Pre-commit hooks (`ruff`, `mypy`, `gitleaks`, `conventional-pre-commit`) prevent low-quality commits from ever entering history.
- **+** Strict typing forces interfaces to be explicit, which compounds in value as the codebase grows.
- **−** Initial setup cost is real (several hours over the first week). One-time, not recurring.

---

## Decision 7 — `structlog` for logging

**Chosen:** structlog with console renderer in development, JSON renderer in production.

**Alternatives considered:**

- **Standard library `logging`.** Always available, no dependency. But unstructured strings are painful to query in production log aggregators. Rejected.
- **`loguru`.** Pleasant API but ties code to its specific call patterns; awkward to switch later. Rejected.

**Consequences:**

- **+** Production logs are JSON, structured, parseable by Loki / Datadog / CloudWatch without regex hell.
- **+** Development logs are human-readable with colors.
- **+** Same logger interface in both modes — no code changes.
- **+** Easy to add contextual bindings (`logger.bind(request_id=...)`) for trace correlation in Phase 4.

---

## Decision 8 — Multi-provider LLM strategy from day one

**Chosen:** The config layer supports OpenAI, Anthropic, Cohere, Groq, and Together. The active provider is chosen at runtime via env var.

**Alternatives considered:**

- **Pin to a single provider.** Simpler. But locks us into one cost/latency/quality tradeoff and one set of model capabilities. Rejected.
- **Use LiteLLM as an abstraction.** Adds a dependency for a problem we can solve with a thin internal adapter. Rejected for now — may revisit if we hit real cross-provider quirks.

**Consequences:**

- **+** Can swap providers without code changes — useful for cost optimization, latency tuning, or capability matching (e.g., Anthropic for long-context analysis, Groq for fast cheap reranking).
- **+** Provider-comparison evaluations in Phase 5 become trivial.
- **−** Slightly more config surface (one set of credentials per provider). Acceptable.

---

## What's deferred

Decisions explicitly *not* made in Phase 1, to be revisited in later phases:

- **Vector DB final commitment.** Qdrant is in the stack but the comparison against Weaviate, Milvus, and pgvector happens in Phase 2 with real data.
- **Embedding model.** Currently configured for `text-embedding-3-large` (OpenAI), but BGE-M3 and `nomic-embed-text` will be benchmarked in Phase 2.
- **Agentic framework.** LangGraph is the working assumption (mature, Anthropic-aligned, good debugging tooling), but the actual choice happens in Phase 3 after a small spike comparing LangGraph vs. CrewAI vs. raw orchestration.
- **Auth.** No authentication in Phase 1. JWT + per-user rate limits land in Phase 4.

---

## References

- The `src/` layout: <https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/>
- uv: <https://docs.astral.sh/uv/>
- Pydantic Settings v2: <https://docs.pydantic.dev/latest/concepts/pydantic_settings/>
- ADR concept (Michael Nygard, 2011): <https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>
