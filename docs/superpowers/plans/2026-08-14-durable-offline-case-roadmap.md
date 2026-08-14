# Durable Offline Case Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a durable, replayable, evidence-bound, multi-period offline case workflow with
manual governed learning and no automatic or live execution path.

**Architecture:** Preserve `run_fixture_case` as the deterministic calculation core. Put every
effect in idempotent PostgreSQL-backed activities and let a pinned Temporal workflow exchange only
typed references and digests. Extend the same fixture boundary incrementally for evidence,
multi-period accounting, risk denials, operator commands, and manual learning.

**Tech Stack:** Python 3.12, Pydantic 2, PostgreSQL 16, Temporal Python SDK, Ed25519, pytest,
Hypothesis, Ruff, mypy, uv.

## Global Constraints

- Supported environments remain exactly `SIM` and `PAPER`; never add `LIVE`.
- No brokers, unrestricted retrieval, remote LLM/model calls, portfolio optimizer, public write
  API, large UI, or automatic learning promotion.
- PostgreSQL tests use only `scripts/test-postgres-migration.sh` ephemeral resources.
- Temporal workflow code performs no I/O, clock reads, random IDs, filesystem access, signing, or
  execution; effects live in idempotent Activities.
- Tenant/case/reference binding, canonical digests, UTC times, `Decimal`, RLS, append-only records,
  and atomic check-and-consume remain fail closed.
- Preserve unrelated user-owned files, especially `Raghav_Badhwar_Comprehensive_CV_2026.pdf`.
- Every behavior change follows red-green TDD; every release slice ends with `scripts/verify.sh`.

---

### Task 1: Stabilize the Current Fixture Candidate

**Files:**
- Modify: `docs/release/M0-security-kernel-validation.md`
- Modify: `docs/BUILD_PLAN.md`
- Review: all changes relative to `64022a2`

**Interfaces:**
- Consumes: current M1-M5 uncommitted fixture candidate.
- Produces: one exact reviewed candidate commit and one validation-record commit naming it.

- [x] **Step 1: Run the current full gate**

Run: `uv lock --check && scripts/verify.sh`

Expected: Ruff, mypy, schemas, pytest, and ephemeral PostgreSQL exit 0; record the exact pytest
count and tool versions from output.

- [x] **Step 2: Request an independent read-only review**

Review every related tracked and untracked file relative to `64022a2`. Exclude the CV PDF and
`docs/superpowers/`. Fix all Critical and Important findings with a failing regression test first
when behavior changes.

- [x] **Step 3: Commit the reviewed candidate**

Stage only the M1-M5 implementation, fixtures, schemas, tests, CI, and matching product docs.
Do not stage the CV or Superpowers planning files.

```bash
git commit -m "feat: complete deterministic offline fixture candidate"
```

- [x] **Step 4: Correct and commit validation evidence**

Replace the stale commit range with the exact Step 3 SHA, replace the obsolete test count with the
fresh count, remove the duplicate open item, and state what was and was not independently reviewed.

```bash
git commit -m "docs: record exact fixture candidate validation"
```

- [x] **Step 5: Re-run the release gate**

Run: `uv lock --check && scripts/verify.sh && git diff --check`

Expected: all checks exit 0 and tracked candidate changes are committed.

---

### Task 2: Add Atomic PostgreSQL Execution Persistence

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `infrastructure/postgres/migrations/0002_durable_offline_execution.sql`
- Modify: `scripts/test-postgres-migration.sh`
- Create: `src/aegisquant/case_ledger/postgres.py`
- Create: `tests/test_postgres_store.py`

**Interfaces:**
- Consumes: `FixtureCaseSpec`, `FixtureCaseReport`, `RiskDecisionPayload`,
  `PaperAccountState`, canonical JSON/digest helpers.
- Produces: `PostgresCaseStore.prepare_case(...) -> DurableCaseRef`,
  `execute_once(...) -> DurableExecutionRef`, and `inspect(...) -> DurableCaseSnapshot`.

- [x] **Step 1: Write failing migration recovery assertions**

Extend the ephemeral shell test to call the same execution idempotency key twice and assert:

```sql
SELECT count(*) FROM consumed_risk_decisions; -- 1
SELECT count(*) FROM paper_execution_results; -- 1
SELECT jsonb_array_length(result_payload->'fills') FROM paper_execution_results; -- exact fill count
```

Then reuse the key with a changed request digest and require a nonzero `psql` exit.

- [x] **Step 2: Run the migration test and observe RED**

Run: `scripts/test-postgres-migration.sh`

Expected: FAIL because the durable execution tables/function do not exist.

- [x] **Step 3: Add the minimum append-only schema**

Add tenant-scoped tables:

```sql
paper_account_snapshots(tenant_id, account_id, state_sequence, snapshot_digest,
                        snapshot_payload, recorded_at)
consumed_risk_decisions(tenant_id, account_id, nonce, decision_digest, consumed_at)
paper_execution_results(tenant_id, case_id, execution_id, idempotency_key, request_digest,
                        result_digest, result_payload, created_at)
```

Add primary/unique keys, digest checks, forced RLS, mutation-rejection triggers, and one
`aq_record_paper_execution(...)` function that serializes by tenant/account/nonce, rejects changed
idempotency content, and returns the original stored row on exact retry.

- [x] **Step 4: Run the migration test and observe GREEN**

Run: `scripts/test-postgres-migration.sh`

Expected: PASS with one consumed decision and one result after exact retry.

- [x] **Step 5: Add the exact PostgreSQL driver pin**

Run: `uv add --bounds exact --no-sync "psycopg[binary]" && uv sync --all-groups`

Review `pyproject.toml` and `uv.lock`; no unrelated package upgrade is accepted.

- [x] **Step 6: Write failing adapter tests**

Tests must prove that `prepare_case` rejects digest reuse, `execute_once` returns the stored result
on exact retry, a changed digest raises `IdempotencyConflict`, and tenant-scoped inspection cannot
cross tenant boundaries.

- [x] **Step 7: Implement the narrow adapter**

Use psycopg parameter binding and transactions. Do not introduce an ORM, connection pool,
repository base class, retry framework, or schema abstraction.

- [x] **Step 8: Run focused and static checks**

Run:

```bash
uv run pytest -q tests/test_postgres_store.py
uv run ruff format --check src/aegisquant/case_ledger/postgres.py tests/test_postgres_store.py
uv run ruff check src/aegisquant/case_ledger/postgres.py tests/test_postgres_store.py
uv run mypy
```

Expected: all exit 0.

---

### Task 3: Add the Pinned Durable Temporal Workflow

**Files:**
- Modify: `src/aegisquant/workflows/contracts.py`
- Modify: `src/aegisquant/workflows/__init__.py`
- Create: `src/aegisquant/workflows/durable_case.py`
- Create: `src/aegisquant/workflows/durable_activities.py`
- Create: `tests/test_durable_case_workflow.py`
- Create: `tests/fixtures/temporal/durable_case_workflow_v1.json`

**Interfaces:**
- Consumes: `DurableCaseRef`, `DurableExecutionRef`, `PostgresCaseStore`.
- Produces: `DurableCaseWorkflowInput`, `DurableCaseWorkflowResult`,
  `DurableOfflineCaseWorkflow`, and activities `prepare_durable_case_v1`,
  `execute_durable_case_v1`, `reconcile_durable_case_v1`.

- [x] **Step 1: Write failing workflow contract and retry tests**

Cover nested tenant/case mismatch, incoherent returned digest, stable activity IDs, and an execution
activity invoked twice after a simulated post-commit failure returning the same execution digest
and fill IDs.

- [x] **Step 2: Run focused tests and observe RED**

Run: `uv run pytest -q tests/test_durable_case_workflow.py`

Expected: FAIL because V1 durable workflow types and activities are absent.

- [x] **Step 3: Implement typed references and idempotent activities**

Each activity receives a small strict contract, calls the injected store, and returns one strict
reference. Use stable deterministic identifiers derived from tenant, case, and input digest.

- [x] **Step 4: Implement the pinned workflow**

The workflow executes prepare, execute, then reconcile with explicit activity IDs, 30-second
start-to-close, 45-second schedule-to-close, maximum two attempts, wait-for-cancellation, and exact
digest/binding checks after every result.

- [x] **Step 5: Capture and test replay history**

Add a golden deterministic history fixture and replay it without any worker/network service.

- [x] **Step 6: Run focused checks**

Run:

```bash
uv run pytest -q tests/test_durable_case_workflow.py tests/test_temporal_replay.py
uv run ruff format --check src/aegisquant/workflows tests/test_durable_case_workflow.py
uv run ruff check src/aegisquant/workflows tests/test_durable_case_workflow.py
uv run mypy
```

Expected: all exit 0.

---

### Task 4: Bind Frozen Evidence to Forecasts and ABSTAIN

**Files:**
- Modify: `src/aegisquant/contracts/research.py`
- Create: `src/aegisquant/intelligence/forecast_evidence.py`
- Modify: `scripts/export_contract_schemas.py`
- Create: `tests/test_forecast_evidence.py`
- Create: `data/fixtures/research/forecast_evidence_control.json`

**Interfaces:**
- Produces: `ForecastEvidenceBundle`, `ForecastAssessment`, and
  `assess_forecast_evidence(bundle, *, as_of) -> ForecastAssessment`.
- `ForecastAssessment.outcome` is exactly `SUPPORTED` or `ABSTAIN`.

- [ ] **Step 1: Write failing support and abstention tests**

Require `SUPPORTED` only with at least two independently identified supporting evidence records,
all numeric claims bound to those records, no unresolved counter-evidence, availability strictly
before cutoff, and exact forecast/evidence digests. One missing condition must yield `ABSTAIN`;
tenant/case/snapshot or digest mismatch must raise.

- [ ] **Step 2: Run and observe RED**

Run: `uv run pytest -q tests/test_forecast_evidence.py`

- [ ] **Step 3: Implement the minimum pure assessment**

Use existing `EvidenceRecord`, `NumericClaim`, `Forecast`, `StrictModel`, and `digest_canonical`.
Do not add retrieval, extraction, model invocation, scoring weights, or learned thresholds.

- [ ] **Step 4: Export schemas and verify GREEN**

Run:

```bash
uv run python scripts/export_contract_schemas.py
uv run pytest -q tests/test_forecast_evidence.py
uv run python scripts/export_contract_schemas.py --check
```

Expected: all exit 0.

---

### Task 5: Add Multi-Period PIT Evaluation and Independent Recompute

**Files:**
- Modify: `src/aegisquant/contracts/research.py`
- Modify: `src/aegisquant/quant/paper.py`
- Modify: `src/aegisquant/quant/pit.py`
- Modify: `src/aegisquant/quant/metrics.py`
- Create: `src/aegisquant/quant/multi_period.py`
- Create: `tests/test_multi_period_case.py`
- Create: `data/fixtures/cases/multi_period_control.json`
- Modify: `scripts/export_contract_schemas.py`

**Interfaces:**
- Produces: `MultiPeriodCaseSpec`, `PeriodResult`, `MultiPeriodCaseReport`,
  `run_multi_period_case(spec) -> MultiPeriodCaseReport`, and
  `verify_multi_period_report(spec, report) -> bool`.

- [ ] **Step 1: Write failing fixture behavior tests**

The frozen fixture must include at least six rebalance dates, a benchmark, one split, one cash
dividend, one delisting-to-cash event, one stale bar rejection, one limit order left unfilled, one
price gap, and both buy and sell fills. Assert literal ending cash/positions/NAV and benchmark
return derived independently from the production helper.

- [ ] **Step 2: Write failing evaluation tests**

Require non-overlapping walk-forward folds, a locked holdout digest, placebo returns, sufficient
observation gating, and tamper detection by `verify_multi_period_report`.

- [ ] **Step 3: Run and observe RED**

Run: `uv run pytest -q tests/test_multi_period_case.py`

- [ ] **Step 4: Implement only fixture-required execution semantics**

Add limit eligibility, explicit unfilled IDs, sells/rebalancing, split quantity adjustment,
dividend cash, delisting liquidation, and stale-data rejection. Preserve long-only/no-leverage
invariants.

- [ ] **Step 5: Implement multi-period orchestration and verification**

Keep period processing deterministic and pure. Recompute the report from immutable fills/actions;
do not trust the report's own totals.

- [ ] **Step 6: Export schemas and run GREEN checks**

Run:

```bash
uv run python scripts/export_contract_schemas.py
uv run pytest -q tests/test_multi_period_case.py tests/test_research_suite.py
uv run python scripts/export_contract_schemas.py --check
uv run mypy
```

Expected: all exit 0.

---

### Task 6: Complete Durable Risk Denial Paths

**Files:**
- Modify: `src/aegisquant/security/risk_signing.py`
- Modify: `src/aegisquant/quant/risk.py`
- Modify: `tests/test_risk_signing.py`
- Modify: `tests/test_multi_period_case.py`
- Modify: `scripts/test-postgres-migration.sh`

**Interfaces:**
- Consumes: existing `ExecutionAuthorizationGate`, signed decision/context, durable consumption.
- Produces no second authorization path.

- [ ] **Step 1: Add failing denial tests**

Cover missing/wrong human approval digest, stale portfolio sequence/snapshot, expired decision,
kill-switch epoch mismatch, rejected order, nonce replay, and changed request after durable commit.
For each failure, assert no account snapshot, decision consumption, or execution result was added.

- [ ] **Step 2: Run and observe RED where a shared guard is missing**

Run:

```bash
uv run pytest -q tests/test_risk_signing.py tests/test_multi_period_case.py
scripts/test-postgres-migration.sh
```

- [ ] **Step 3: Fix only shared enforcement points**

Put authorization fixes in `ExecutionAuthorizationGate` or its durable consumption boundary and
policy fixes in the shared risk evaluator. Do not add runner-specific duplicate guards.

- [ ] **Step 4: Run GREEN checks**

Repeat Step 2. Expected: all exit 0.

---

### Task 7: Add Operator Run, Verify, Replay, Inspect, and Readiness

**Files:**
- Modify: `pyproject.toml`
- Create: `src/aegisquant/case_cli.py`
- Modify: `src/aegisquant/control_api.py`
- Create: `tests/test_case_cli.py`
- Modify: `tests/test_control_api.py`
- Modify: `README.md`

**Interfaces:**
- Produces: console command `aegisquant-case` with `run`, `verify`, `replay`, `inspect`.
- Preserves: `run-fixture-case` compatibility.
- Produces: `GET /health/ready`; no execution/write endpoint.

- [ ] **Step 1: Write failing CLI behavior tests**

Use real temporary fixture/report files. Assert `run` emits a deterministic report, `verify`
detects one-byte tamper, `replay` returns the same durable digest, `inspect` performs no writes,
and invalid JSON exits 2 with one concise error.

- [ ] **Step 2: Write failing readiness tests**

Inject dependency probes and assert 200 only when PostgreSQL and Temporal probes are ready, 503
otherwise. Assert the OpenAPI paths contain no execution, broker, order, ingestion, or mutation
route.

- [ ] **Step 3: Run and observe RED**

Run: `uv run pytest -q tests/test_case_cli.py tests/test_control_api.py`

- [ ] **Step 4: Implement argparse dispatch and readiness**

Reuse `FixtureCaseSpec`, `run_fixture_case`, verification helpers, and strict report contracts.
Do not add Click/Typer, a service container, or a case API.

- [ ] **Step 5: Run GREEN checks**

Run:

```bash
uv run pytest -q tests/test_case_cli.py tests/test_control_api.py
uv run aegisquant-case --help
uv run run-fixture-case data/fixtures/cases/multi_asset_control.json
```

Expected: all exit 0; compatibility output remains deterministic.

---

### Task 8: Connect Governed Learning Without Automatic Promotion

**Files:**
- Modify: `src/aegisquant/contracts/learning.py`
- Modify: `src/aegisquant/learning/governance.py`
- Create: `src/aegisquant/learning/loop.py`
- Create: `tests/test_learning_loop.py`
- Modify: `scripts/export_contract_schemas.py`
- Modify: `src/aegisquant/case_cli.py`

**Interfaces:**
- Produces: `LearningProposalManifest`, `LearningCycleResult`,
  `propose_candidate(...) -> LearningCycleResult`, and
  `verify_approved_candidate(...) -> LearningProposalManifest`.
- `LearningCycleResult.outcome` is exactly `ABSTAIN` or `CANDIDATE`.

- [ ] **Step 1: Write failing abstention and proposal tests**

An insufficient, immature, unlocked, or non-independent outcome must return `ABSTAIN` and no
candidate. A sufficient matured outcome creates a candidate bound to source, baseline, proposal,
evaluation plan, and rollback digests.

- [ ] **Step 2: Write failing promotion/application tests**

Approval must reject wrong tenant/case/candidate/evaluation/proposal/rollback binding, failed
shadow/canary, and non-human approver. An exact approved allowlisted strategy proposal may change
only a later fixture strategy parameter; risk policy, permissions, thresholds, and holdout remain
unchanged. No function applies an unapproved candidate.

- [ ] **Step 3: Run and observe RED**

Run: `uv run pytest -q tests/test_learning_loop.py`

- [ ] **Step 4: Implement the minimal loop around existing governance**

Reuse `LearningCandidate`, `evaluate_candidate`, and `approve_candidate`; add proposal binding and
ABSTAIN orchestration only. Do not add training, online updates, autonomous proposal generation,
or automatic promotion.

- [ ] **Step 5: Add CLI lifecycle commands**

Add `learning propose`, `learning evaluate`, `learning approve`, and `learning verify` as offline
JSON-in/JSON-out operations. Approval creates a record only; it never runs a case automatically.

- [ ] **Step 6: Export schemas and run GREEN checks**

Run:

```bash
uv run python scripts/export_contract_schemas.py
uv run pytest -q tests/test_learning_loop.py tests/test_research_suite.py
uv run python scripts/export_contract_schemas.py --check
uv run mypy
```

Expected: all exit 0.

---

### Task 9: Final Verification, Independent Review, and Validated Commits

**Files:**
- Modify: `docs/BUILD_PLAN.md`
- Modify: `docs/release/M0-security-kernel-validation.md`
- Create: `docs/release/durable-offline-case-validation.md`

**Interfaces:**
- Produces: source-bound validation evidence; no production-readiness claim.

- [ ] **Step 1: Run exact reproducibility and recovery checks**

Run the control fixture twice and compare bytes. Run the ephemeral PostgreSQL interruption/retry
scenario and query exact counts for decisions, executions, and fills.

- [ ] **Step 2: Run the full gate**

Run:

```bash
uv lock --check
scripts/verify.sh
git diff --check
```

Expected: all exit 0.

- [ ] **Step 3: Request independent whole-diff review**

Fix all Critical and Important findings under TDD, then repeat Step 2 and request a scoped
re-review.

- [ ] **Step 4: Record evidence without overclaiming**

Document exact commands, tool versions, test count, PostgreSQL recovery counts, Temporal replay
coverage, limitations, and the commit SHA being validated. Keep production, performance, custody,
customer, and live-readiness claims explicitly out of scope.

- [ ] **Step 5: Commit release-sized slices**

Use scoped Conventional Commit subjects. Do not push, merge, deploy, or create a PR without a new
operator instruction.
