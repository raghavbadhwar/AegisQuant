# Durable Offline Case Roadmap Design

**Status:** Approved by the operator in the 2026-08-14 implementation request.

## Objective

Turn the current deterministic, process-local fixture runner into a durable offline case system
that can recover from interruption without duplicate authorization or fills, then extend that same
fixture boundary with evidence validation, multi-period evaluation, complete risk paths, operator
inspection commands, and manually governed learning.

The supported profile remains one local operator, PostgreSQL, Temporal, frozen fixtures, and
`SIM`/`PAPER` contracts. This work does not authorize production or live trading.

## Chosen architecture

Keep `run_fixture_case` as the deterministic calculation core. Move effects into idempotent
activities backed by PostgreSQL and coordinate only small typed digests/references in a new pinned
Temporal workflow. The workflow never performs database, filesystem, clock, random, signing, or
execution work directly.

Reuse the existing PostgreSQL case ledger and `aq_record_idempotency` semantics. Add only durable
tables needed by the acceptance test: account snapshots, consumed risk decisions, and immutable
paper execution results. A database transaction must atomically consume the decision, persist the
result, and append its execution event. Repeating the same request returns the stored result;
reusing the idempotency key with different content fails closed.

This is preferred to putting the runner inside workflow code, which would break replay
determinism, and to rebuilding the system as a general event-sourcing framework, which is not
needed for the current local fixture milestone.

## Release phases

### 1. Candidate stabilization

- Classify every current tracked and untracked path.
- Preserve unrelated user files and caches; do not silently delete them.
- Correct the stale validation record, including the duplicate open item and obsolete test count.
- Run the full repository gate and an independent diff review.
- Commit the exact reviewed fixture candidate before durability changes begin.

### 2. Durable execution and recovery

- Add append-only/RLS PostgreSQL records for account snapshots, consumed decisions, and execution
  results.
- Add one atomic database function for check-and-consume plus result persistence.
- Implement a narrow PostgreSQL adapter behind existing execution/ledger contracts; do not add a
  general ORM or repository framework.
- Add typed Temporal V3 inputs/results and idempotent activities for prepare, authorize/execute,
  reconcile, and inspect.
- Use stable activity IDs, bounded retry/timeouts, and exact digest checks on every returned
  reference.
- Prove interruption before and after authorization by retrying activities against the same
  ephemeral database and observing one decision consumption, one execution result, and one set of
  fills.

### 3. Evidence-to-forecast validation

- Add a frozen forecast-evidence bundle that binds evidence IDs/digests, numeric claims,
  counter-evidence, forecast, and evaluation cutoff.
- Reject tenant/case/snapshot mismatch, unavailable evidence, unbound claims, and tampered
  digests.
- Produce `ABSTAIN` when minimum independent support is absent or unresolved counter-evidence
  remains. Forecast creation stays deterministic and fixture-only.

### 4. Multi-period evaluation

- Add a versioned fixture containing multiple rebalance dates, a benchmark, split, dividend,
  delisting, stale observation, price gap, and limit/unfilled order.
- Extend the paper calculation only where the fixture requires it: sells/rebalancing, corporate
  action accounting, limit eligibility, and explicit unfilled results.
- Produce walk-forward and locked-holdout reports plus a deterministic placebo comparison.
- Independently recompute cash, positions, benchmark return, and reported performance from the
  immutable period ledger.

### 5. Complete risk workflow

- Exercise required human-approval digests and kill-switch epochs through the durable path.
- Cover rejected orders, stale snapshots, expired decisions, sells, rebalancing, and nonce replay.
- Keep risk limits, permissions, approval requirements, holdouts, and evaluation thresholds
  outside the learning surface.

### 6. Operator usability

- Replace the single-purpose console entry point with one `aegisquant-case` command exposing
  `run`, `verify`, `replay`, and `inspect` subcommands. Preserve `run-fixture-case` as a compatible
  alias during this milestone.
- `verify` recomputes digests and accounting without mutation. `replay` uses frozen inputs and
  durable idempotency keys. `inspect` is read-only.
- `/health/ready` reports dependency readiness without creating an execution route. No write API
  or order endpoint is added.

### 7. Governed learning

- Convert only matured, sufficient multi-period outcomes into candidates.
- Bind each proposal to its baseline, locked evaluation manifest, rollback manifest, and source
  outcome.
- Require independent shadow and canary evaluation plus an explicit manual approval record.
- An approved allowlisted strategy candidate may affect a later fixture run only after exact
  approval/evaluation/proposal digest verification. Automatic promotion remains impossible.
- Insufficient evidence produces `ABSTAIN` and no candidate.

## Data flow

1. The operator submits a frozen fixture case and a stable idempotency key.
2. A prepare activity validates contracts and stores the case/input digest.
3. The workflow receives only the prepared reference and verifies its exact digest.
4. An execution activity loads the frozen input, computes the deterministic order/risk bundle,
   verifies authorization, and atomically records consumption plus the immutable result.
5. A reconciliation activity independently recomputes the account and stores a verification
   event.
6. Replay or retry returns the same stored references. Changed input under an existing key is an
   idempotency conflict.
7. Research, evaluation, and learning consume immutable result digests; none edits an earlier
   case result.

## Failure semantics

- Validation, tenant/case binding, digest, chronology, authorization, and reconciliation failures
  are non-retryable and fail closed.
- Transient database/activity failures use bounded Temporal retries.
- A crash before the atomic execution transaction leaves no consumed decision or result.
- A crash after commit returns the already stored result on retry and cannot emit duplicate fills.
- A partial or incoherent activity reference causes the workflow to stop rather than continue.
- Read-only verification never repairs or mutates records.

## Verification strategy

Use strict TDD for each behavior: first observe the focused test fail for the missing boundary,
then add the minimum implementation, then run the focused suite. Every contract change regenerates
and checks its JSON Schema. Migration changes run only against the repository's ephemeral
PostgreSQL harness. Temporal changes require deterministic unit tests and replay coverage without
starting a network worker. Each release slice ends with `scripts/verify.sh`, `git diff --check`, and
an independent diff review before its validated commit is recorded.

## Explicit exclusions

No broker adapter, `LIVE` environment, unrestricted retrieval, remote model/provider call,
portfolio optimizer, public ingress, execution API, large UI, new orchestration framework, or
automatic strategy/policy/permission promotion is part of this roadmap.
