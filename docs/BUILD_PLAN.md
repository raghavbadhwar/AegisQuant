# Build plan

Status legend: `[ ]` not started, `[~]` active, `[x]` verified.

Supported profile: **personal and local-first** — one workstation and operator, local services, no public ingress, and no enterprise cluster requirement. Logical tenant scoping remains for portfolio/experiment isolation and defense in depth. See ADR-0003.

## M0 — security kernel (active)

- [x] Consolidated architecture reviewed by independent engineering, quant, risk, execution, and security roles.
- [x] Scope locked to fixture-only research plus simulation/paper contracts.
- [x] Strict shared contracts with tenant, environment, chronology, provenance, rights, and content digests.
- [x] Append-only hash-chained case ledger with idempotency conflict detection.
- [x] Capability reference-monitor core with deny-by-default authorization.
- [x] Asymmetric, domain-separated exact-order risk decision contract and verifier.
- [x] PostgreSQL migrations, bound-role forced RLS, non-owner roles, and cross-tenant tests.
- [x] Immutable object-store interface, local reference backend, metadata/retention integrity tests.
- [ ] Temporal replay-safe golden workflow and crash/idempotency tests.
- [ ] CI supply-chain gates, SBOM, image digests, secret/license/vulnerability scanning.
- [x] Independent adversarial re-audit of the implemented M0 slice (no P0/P1 blockers).

## M1 — reproducible research case

- Fixture/canonical-source-only evidence pipeline.
- Frozen data/relation/memory/skill/model manifests.
- Evidence auditor and forecast verifier using recorded model fixtures first.
- Forensic replay with networking disabled and identical artifact/event hashes.

## M2 — controlled intelligence

- Egress-proxied Source Gateway and rights engine.
- Last30Days and Scrapling only behind typed, exact-domain allowlisted adapters; runtime installation disabled.
- Quarantine, malware/active-content controls, injection taint, and capability mediation.
- PydanticAI under Temporal; LiteLLM alias allowlist and privacy policy.
- GBrain adapter as a derived projection only.

## M3 — quant control experiment

- PIT security master, calendars, corporate actions, trial ledger, and data snapshots.
- One pre-registered daily SPY/cash deterministic control strategy; no optimizer, behavior, graph, leverage, shorting, or claimed alpha.
- Cash, distribution, cost, walk-forward, placebo, multiple-testing, and independent accounting checks.

## M4 — hard risk and paper execution

- Policy-as-data compiler and deterministic rule engine.
- Signed exact-order authorization, one-time atomic consumption, kill epochs, and human approval proof.
- NautilusTrader isolated paper adapter only after LGPL and adapter due diligence.
- Reconciliation, uncertain-outcome handling, TCA, and chaos tests.

## M5 — governed learning

- Horizon-matured attribution, learning candidates, independent evaluation, shadow/canary, rollback.
- No automatic promotion for prompts, skills, routes, features, strategies, risk, or permissions.

## M6 — live-readiness assessment (not authorization)

Requires jurisdiction-specific legal/compliance determination, data contracts, broker/venue rules, model validation, security certification, operational runbooks, human governance, and explicit user approval. Live trading is not implied by completion of earlier milestones.
