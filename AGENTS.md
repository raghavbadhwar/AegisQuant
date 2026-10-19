# Repository Guidelines

## Project Structure & Module Organization

Application code lives in `src/aegisquant/`. Keep domain contracts in `contracts/`, ledger logic in `case_ledger/`, authorization and signing in `security/`, routing in `intelligence/`, durable storage in `object_store/`, and Temporal code in `workflows/`. Tests mirror these concerns under `tests/test_*.py`; deterministic replay inputs belong in `tests/fixtures/`. Versioned JSON Schemas live in `data/schemas/`, PostgreSQL migrations in `infrastructure/postgres/migrations/`, operational scripts in `scripts/`, and design or release records in `docs/`.

## Build, Test, and Development Commands

- `uv sync --all-groups` installs the locked Python 3.12–3.13 runtime and development tools.
- `uv run uvicorn aegisquant.control_api:app --reload` starts the local control API.
- `uv run pytest -q` runs the Python test suite; add a path such as `tests/test_risk_signing.py` for a focused run.
- `uv run ruff format --check . && uv run ruff check . && uv run mypy` checks formatting, lint, imports, security rules, and strict typing.
- `uv run python scripts/export_contract_schemas.py --check` detects stale generated schemas. Run it without `--check` after an intentional contract change.
- `scripts/verify.sh` runs the full gate, including schema and ephemeral PostgreSQL migration checks. It requires a local PostgreSQL server and `psql` privileges.

## Coding Style & Naming Conventions

Use four-space indentation, Python 3.12 syntax, complete type annotations, and a 100-character line limit. Ruff owns formatting and linting; mypy runs in strict mode. Name modules and functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`, and tests `test_<behavior>`. Preserve strict Pydantic boundaries and deterministic serialization.

## Testing Guidelines

Use pytest, `pytest-asyncio`, and Hypothesis where property tests add value. Every behavior change needs a focused success or denial-path regression test. No numeric coverage threshold is configured; prioritize security boundaries, tenant isolation, idempotency, replay determinism, and tamper rejection.

## Commit & Pull Request Guidelines

Follow the existing Conventional Commit-style subjects, such as `feat: establish ...` or `docs: record ...`. Keep commits scoped. Pull requests should explain the behavior and safety impact, link the issue or milestone, list checks actually run, and call out schema, migration, or release-boundary changes.

## Security & Release Boundaries

M0 is fixture-only research and simulation/paper contracts. Do not add live trading, broker adapters, unrestricted ingestion, credentials, or production-readiness claims without an approved milestone and explicit review. Never commit secrets or private/licensed data.

## Architecture Map

- `contracts/` is the trust boundary. `StrictModel` is immutable, forbids extra fields, validates
  defaults, normalizes Unicode, requires UTC timestamps, and uses typed canonical serialization.
  Keep contract schema versions explicit; update generated JSON Schemas with
  `scripts/export_contract_schemas.py` when contracts change.
- `security/` owns canonical digests, capability authorization, and Ed25519 risk verification.
  The execution authorization gate verifies an exact order-bundle digest, all contextual snapshot
  bindings, signature/key validity, time window, and one-time nonce consumption.
- `case_ledger/` is the append-only event reference implementation. PostgreSQL's migration must
  remain byte-for-byte compatible with the Python event-content and chain-digest algorithms.
- `object_store/` provides a tenant-scoped, content-addressed local immutable reference backend.
  It is deliberately not a production WORM claim.
- `intelligence/depth_router.py` is deterministic escalation only: it may deepen research but
  must not silently reduce the requested mode.
- `workflows/` is the sole durable orchestration owner. `ResearchCaseWorkflowV1` coordinates only
  fixture activities and exchanges small typed references/digests, never raw evidence payloads.
  Its history is pinned, replayed against `tests/fixtures/temporal/`, and workflow identity is
  tenant-bound.
- `control_api.py` is intentionally a health-only M0 control plane. It must not expose execution,
  broker, order, or ingestion routes.

## Non-Negotiable Invariants

- M0 permits only `SIM` and `PAPER`. Do not add `LIVE`, broker SDKs/adapters, broker endpoints,
  credentials, unrestricted network ingestion, remote-model paths, or claims of live readiness.
- Tenant identity is authenticated context at enforcement boundaries, not an LLM-supplied value.
  Bind every nested reference, database key, object access, workflow ID, grant, and result to its
  tenant (and case where relevant); reject mismatches before downstream work.
- Preserve deterministic canonicalization: no binary floats in signed/digested payloads; use
  `Decimal`, explicit UTC datetimes, NFC strings, and `digest_canonical` rather than ad-hoc JSON
  or hashes.
- Authorization is deny-by-default and check-and-consume must be atomic. Preserve grant
  revocation, exact hostname allowlists, required scope/domain/privilege checks, and call/cost
  budgets.
- Risk authorization is fail closed. Never weaken exact-bundle, epoch, state-manifest,
  signature/key-revocation, expiry, or single-use verification.
- Ledger and authoritative migration tables are append-only. Do not loosen RLS, non-owner role
  separation, mutation-rejection triggers, idempotency conflict handling, or chain validation.
- Temporal workflows must remain replay deterministic: no I/O, clocks, random UUIDs, filesystem
  access, or mutable global state in workflow code. Put effects in idempotent Activities; use
  stable activity IDs, bounded retries/timeouts, typed inputs/results, and fail closed on an
  incoherent activity result. Deliberate history changes require a new versioning/replay plan and
  an explicitly accepted golden-fixture update.

## Change Procedure

1. Read the relevant ADR, contract, implementation, and mirrored tests before changing a boundary.
2. Make the smallest compatible change. A contract, digest, SQL, workflow, or policy change needs
   success and denial/tamper/replay regression coverage as applicable.
3. For contract changes, regenerate schemas and review the resulting `data/schemas/` diff. For
   Python/PostgreSQL shared digest changes, add/maintain a cross-implementation golden test.
4. Validate proportionately with focused tests first, then run:
   `uv run pytest -q`, `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, and
   `uv run python scripts/export_contract_schemas.py --check`. Run `scripts/verify.sh` when
   PostgreSQL is available or when changing migrations/security boundaries.
5. Treat current uncommitted work as user-owned: inspect `git status`/`git diff` and do not revert
   unrelated changes. Do not edit generated caches, `.venv`, lockfiles (unless dependency intent
   requires it), or fixture histories without explicit review.


## AegisQuant Agent and Tool Routing (M0)

Agent tooling is development-only; it is not an AegisQuant runtime capability or evidence source.

| Work | Allowed tool/skill | Required guardrail |
| --- | --- | --- |
| Inspect, design, or review | Local filesystem plus `git status`, `git diff`, and `git log` | Read-only by default; preserve user-owned uncommitted work. |
| Python, contracts, and security | `uv run pytest -q <focused-path>`, Ruff, mypy, and schema-export check | Trust-boundary changes require success and denial/tamper coverage. |
| PostgreSQL/migrations | `scripts/test-postgres-migration.sh` or `scripts/verify.sh` | Use only its ephemeral database resources; never mutate a non-ephemeral database ad hoc. |
| Temporal | Fixture activities and `tests/test_temporal_*.py` | Workflows contain no I/O, clocks, random IDs, filesystem access, or worker/network services. |
| Engineering process | Installed `gstack` review/QA/ship process | Apply proportionately to code changes; it does not authorize runtime capabilities. |
| Design research explicitly requested by the operator | `agent-researcher` with primary sources recorded in `docs/` | Isolate it from fixture evidence and runtime inputs. |

M0 must not add or invoke MCP servers, browser/web retrieval, Agent Reach, Scrapling, GBrain,
remote-model/LiteLLM/Codex provider calls, credentials, broker/data-provider SDKs, Docker/cloud
services, runtime-installed packages, or any live/paper order action. A future M2+ integration
requires an ADR, explicit operator approval, a typed capability ID/scope/exact-domain allowlist,
fixture/replay tests, and adversarial denial coverage before activation.
