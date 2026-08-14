# Build plan

Status legend: `[ ]` not started, `[~]` active, `[x]` verified.

Supported profile: **personal and local-first** — one workstation and operator, local services, no public ingress, and no enterprise cluster requirement. Logical tenant scoping remains for portfolio/experiment isolation and defense in depth. See ADR-0003.

## M0 — security kernel (verified offline candidate)

- [x] Consolidated architecture reviewed by independent engineering, quant, risk, execution, and security roles.
- [x] Scope locked to fixture-only research plus simulation/paper contracts.
- [x] Strict shared contracts with tenant, environment, chronology, provenance, rights, and content digests.
- [x] Append-only hash-chained case ledger with idempotency conflict detection.
- [x] Capability reference-monitor core with deny-by-default authorization.
- [x] Asymmetric, domain-separated exact-order risk decision contract and verifier.
- [x] PostgreSQL migrations, bound-role forced RLS, non-owner roles, and cross-tenant tests.
- [x] Immutable object-store interface, local reference backend, metadata/retention integrity tests.
- [x] Temporal replay-safe golden workflow and crash/idempotency tests.
- [x] CI supply-chain gates, SBOM, secret/license/vulnerability scanning; PostgreSQL remains a local ephemeral gate.
- [x] Independent adversarial re-audit closed P0/P1 blockers for exact commit `a6a70b3`;
  the complete durable offline candidate through `2f05a8c` has separate exact validation below.

## M1 — reproducible research case and recovery (verified)

- [x] Frozen `ResearchManifest` and `DataSnapshot` bind the fixture bars, securities, and forecasts.
- [x] Pinned V1/V2 Temporal histories replay offline from committed golden fixtures.
- [x] Frozen evidence, numeric claims, counter-evidence, forecast verification, and explicit
  `ABSTAIN` are exercised with recorded fixtures only.
- [x] PostgreSQL-backed case events, account state, atomic nonce/result writes, and reconciliation.
- [x] Tenant-bound Temporal workflow with stable activity IDs, bounded retries, golden replay, and
  injected failures before and after authorization/reconciliation commits.

## M2 — controlled intelligence (recorded adapter foundation)

- [x] Typed Last30Days recorded-output contract binds the recorded receipt, immutable content digest, tenant, case, snapshot, manifest, and availability time.
- [x] Last30Days result binding rejects wrong-tool receipts and tampered captured content; no runtime transport or source gateway is present in M0.
- [x] The executable research path consumes frozen local evidence and emits verified forecast or
  `ABSTAIN`; no remote model or retrieval path is enabled.
- [ ] Live retrieval remains disabled. It requires a separately verified proxy enforcing robots/rights, DNS/public-address checks, exact tenant/case hostname grants, quotas, and no redirects. Direct Last30Days/Scrapling execution remains prohibited.

## M3 — quant control experiment (verified multi-period fixture)

- [x] PIT security master, availability timestamps, corporate-action helpers, trial records, and data snapshots.
- [x] Multi-asset, deterministic, long-only fixture control with explicit residual cash; no optimizer, leverage, shorting, or alpha claim.
- [x] Costs, cash, future-data rejection, deterministic bootstrap/window/placebo primitives, and
  underpowered-result suppression.
- [x] Integrated corporate actions, benchmark, walk-forward, locked holdout, placebo, delisting,
  stale data, price gaps, limit/unfilled orders, costs, and independent multi-period recomputation.

## M4 — hard risk and paper execution (verified durable offline path)

- [x] Policy-as-data compiler and deterministic pre/post-trade rule engine.
- [x] Signed exact-order authorization, scoped account/data/reference/policy bindings, one-time
  in-memory consumption, kill epochs, and signed human-approval verification.
- [x] Local deterministic paper venue; NautilusTrader remains excluded pending LGPL review.
- [x] Next-bar timing, reconciliation, transaction-cost, and core denial-path coverage.
- [x] Durable atomic nonce consumption/results plus stale snapshots, expiry, kill-switch epoch,
  human-approval digest, sell/rebalance, rejected-order, and recovery denial paths.

## M5 — governed learning (verified manual loop)

- [x] Verified sufficient multi-period outcomes create exact source/baseline/holdout/evaluation/
  rollback-bound candidates; unsupported outcomes return `ABSTAIN`.
- [x] Role-, tenant-, time-, expiry-, and revocation-scoped Ed25519 evaluator and human-approver
  attestations with separation of duties.
- [x] No automatic promotion for prompts, skills, routes, features, strategies, risk, or permissions.
- [x] Exact manual promotion may alter only the allowlisted next-run uncertainty floor after
  independent evaluation; baseline case/digest and rollback bindings fail closed.

## Exact durable-offline candidate validation

- [x] Code commit `2f05a8c593ecf1d0d1ba254d12a2690d4beebdf7`.
- [x] `scripts/verify.sh`: Ruff format/lint, mypy, schema check, 168 tests, and ephemeral PostgreSQL
  migration/RLS/chain/idempotency/append-only checks all passed on 2026-08-14.
- [x] Independent whole-candidate read-only review returned `READY` after closure of offline-network,
  holdout-state, OOS/control, terminal-delisting, signed-attestation, and backdating blockers.

## M6 — live-readiness assessment (not authorization)

Requires jurisdiction-specific legal/compliance determination, data contracts, broker/venue rules, model validation, security certification, operational runbooks, human governance, and explicit user approval. Live trading is not implied by completion of earlier milestones.
