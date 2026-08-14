# AegisQuant OS

AegisQuant is an evidence-first investment research operating system. This repository is being built as four business services—Intelligence, Quant, Hard-Risk, and Execution—around a shared finance-specific harness.

## Current release boundary

**Milestone M0: security kernel and reproducible fixture-only research.**

- Simulation and paper schemas only; `LIVE` is intentionally absent.
- No broker adapter, broker hostname, broker credential, or order-submission API.
- No unrestricted web ingestion, cookie-authenticated channel, or licensed/private dataset.
- No autonomous production memory, skill, prompt, route, strategy, or risk-policy promotion.
- No performance, alpha, capacity, compliance, or live-readiness claim.

The first executable slice implements strict typed contracts, tenant scoping, an append-only/hash-chained case ledger, deterministic research-depth routing, bitemporal evidence eligibility, capability authorization, and exact-order risk-decision signing/verification.

## Quick start

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy
uv run uvicorn aegisquant.control_api:app --reload
uv run aegisquant-case run data/fixtures/cases/multi_asset_control.json --output report.json
uv run aegisquant-case verify data/fixtures/cases/multi_asset_control.json report.json
uv run aegisquant-case replay data/fixtures/cases/multi_asset_control.json report.json
uv run aegisquant-case inspect report.json
uv run aegisquant-case learning propose propose.json
uv run aegisquant-case learning evaluate evaluate.json
uv run aegisquant-case learning approve approve.json
uv run aegisquant-case learning verify verify.json
uv run run-fixture-case data/fixtures/cases/multi_asset_control.json
```

`aegisquant-case` runs, verifies, replays, and inspects strict local report files. `verify` and
`inspect` are read-only; `replay` recomputes the PostgreSQL-compatible durable result digest from
the frozen fixture. `run-fixture-case` remains a compatible alias that executes one fully offline,
deterministic fixture path through frozen
forecasts, portfolio construction, signed risk authorization, paper fills, reconciliation,
the append-only reference ledger, and an explicitly underpowered performance report.

`/health/live` reports process liveness. `/health/ready` returns ready only when
`AEGISQUANT_POSTGRES_DSN`, `AEGISQUANT_TEMPORAL_TARGET`, `AEGISQUANT_TEMPORAL_NAMESPACE`, and
`AEGISQUANT_TEMPORAL_BUILD_ID` are configured. PostgreSQL must expose the tenant-bound durable
schema and read privileges; Temporal must expose the configured namespace and matching
`aegisquant-m0` deployment version on the durable task queue. The API remains health-only and
exposes no mutation or execution route.

The `learning` commands consume strict local JSON and emit immutable proposal, evaluation, and
manual approval records. `learning verify` checks their deterministic bindings but deliberately
returns `promotion_authorized: false`; applying a candidate additionally requires trusted,
role-scoped Ed25519 evaluator and human-approver attestations. The commands never train, promote,
or run a case automatically. Only that fully attested strategy proposal can later change the
allowlisted forecast uncertainty floor; risk policy, permissions, evaluation thresholds, and
locked holdouts remain outside the learning path.

See [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md), [`docs/architecture/ADR-0001-security-kernel-first.md`](docs/architecture/ADR-0001-security-kernel-first.md), and [`docs/research/design-validation-2026-08-08.md`](docs/research/design-validation-2026-08-08.md).

## Safety

This software is under development and is not investment advice. It is not approved for live trading, client assets, regulated activity, or unrestricted/private data.
