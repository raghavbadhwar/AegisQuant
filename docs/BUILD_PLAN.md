# Build plan

Status legend: `[ ]` not started, `[~]` active, `[x]` verified.

Supported profile: **personal and local-first** — one workstation and operator, local services, no public ingress, and no enterprise cluster requirement. Logical tenant scoping remains for portfolio/experiment isolation and defense in depth. See ADR-0003.

## M0 — security kernel (historical commit verified; current candidate pending)

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
  later candidate changes require their own closure review.

## M1 — reproducible research case (verified foundations; durable integration pending)

- [x] Frozen `ResearchManifest` and `DataSnapshot` bind the fixture bars, securities, and forecasts.
- [x] Pinned V1/V2 Temporal histories replay offline from committed golden fixtures.
- [~] Evidence records and artifacts have strict contracts and fixture activities, but the executable
  case still does not carry evidence through one durable workflow.
- [ ] PostgreSQL-backed case recovery and exactly-once paper result persistence.

## M2 — controlled intelligence (recorded adapter foundation)

- [x] Typed Last30Days recorded-output contract binds the gateway receipt, immutable content digest, tenant, case, snapshot, manifest, and availability time.
- [x] Last30Days result binding rejects wrong-tool receipts and tampered captured content; the existing gateway enforces typed capability, exact domains, quotas, and redirect denial.
- [ ] Live retrieval remains disabled. It requires a separately verified proxy enforcing robots/rights, DNS/public-address checks, exact tenant/case hostname grants, quotas, and no redirects. Direct Last30Days/Scrapling execution remains prohibited.

## M3 — quant control experiment (verified primitives; multi-period evaluation pending)

- [x] PIT security master, availability timestamps, corporate-action helpers, trial records, and data snapshots.
- [x] Multi-asset, deterministic, long-only fixture control with explicit residual cash; no optimizer, leverage, shorting, or alpha claim.
- [x] Costs, cash, future-data rejection, deterministic bootstrap/window/placebo primitives, and
  underpowered-result suppression.
- [ ] Integrated corporate actions, benchmark, walk-forward, locked holdout, placebo, delisting,
  limit/unfilled orders, and independent multi-period recomputation.

## M4 — hard risk and paper execution (verified fixture path; durable risk workflow pending)

- [x] Policy-as-data compiler and deterministic pre/post-trade rule engine.
- [x] Signed exact-order authorization, scoped account/data/reference/policy bindings, one-time
  in-memory consumption, kill epochs, and signed human-approval verification.
- [x] Local deterministic paper venue; NautilusTrader remains excluded pending LGPL review.
- [x] Next-bar timing, reconciliation, transaction-cost, and core denial-path coverage.
- [ ] Durable atomic nonce consumption/results plus full stale/expiry/rejection/rebalance recovery matrix.

## M5 — governed learning (verified governance primitives; loop pending)

- [x] Horizon-matured candidate, declared evaluator record, caller-supplied shadow/canary results,
  chronology, and rollback-bound approval contracts/helpers.
- [ ] Authenticated evaluator identity and evaluator/approver separation of duties.
- [x] No automatic promotion for prompts, skills, routes, features, strategies, risk, or permissions.
- [ ] Connect sufficient multi-period outcomes to candidate proposal, manual promotion, rollback,
  and exact next-run verification.

## M6 — live-readiness assessment (not authorization)

Requires jurisdiction-specific legal/compliance determination, data contracts, broker/venue rules, model validation, security certification, operational runbooks, human governance, and explicit user approval. Live trading is not implied by completion of earlier milestones.
