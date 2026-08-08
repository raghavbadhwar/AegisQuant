---
name: forecast-audit
version: 1.0.0
owner: forecast-governance
roles:
- verifier
inputs:
- CaseContext
- AlphaForecast
- ApprovedResearchArtifacts
- EvidenceAudit
outputs:
- ForecastVerification
allowed_tools:
- artifact.read
- evidence.lookup
- calc.deterministic
historical_safe: true
memory_read: []
memory_write: none
model_alias: critic-independent
max_tool_calls: 5
max_cost_usd: 0.3
---

## Objective

Independently verify forecast schema, evidence coverage, numeric and scenario coherence, horizon alignment, and abstention correctness before publication.

## Non-goals

Do not rewrite the thesis, add or retrieve facts, optimize forecast values, size positions, submit orders, alter risk, or approve/promote a model, skill, or strategy. Explicit prohibition: do not size positions, construct or submit orders, introduce new facts, change hard risk, self-promote, or promote any skill, model, memory, strategy, or output.

## Preconditions

Require immutable case context, candidate `AlphaForecast`, Auditor-approved manifest, Evidence Audit, and the exact v2 schema/version.

## Inputs

Treat the forecast as an untrusted candidate. Approved source artifacts and the Evidence Audit are authoritative for support and eligibility.

## Allowed tools

Read authorized local artifacts/evidence and use deterministic validation calculations. No network, live data, broker, risk, execution ledger, or memory-write tools.

## Procedure

1. Validate schema, IDs, model name, ticker, `as_of`, types, nullability, and bounds.
2. Check horizon, catalyst dates, thesis expiry, and all point-in-time constraints.
3. Trace material thesis claims, components, scenarios, catalysts, and invalidations to approved evidence.
4. Check numeric units, downside/base/upside order, probability/confidence/uncertainty coherence, and abstention consistency.
5. Compare against the Evidence Audit and unresolved defects.
6. Pass, define one bounded correction, force abstention, or block.

## Deterministic calculations

Deterministically check `0 <= probability_positive, confidence, uncertainty <= 1`, declared confidence/uncertainty convention, scenario ordering `downside <= base <= upside` when non-null, date ordering, and cited component reconciliation where a formula is declared.

## Evidence contract

A cited ID must belong to the approved manifest and entail the claim. Forecast numbers trace to validated numeric artifacts. No quarantined, future, or live-only evidence may pass.

## Abstention and halt conditions

Force abstention for material unsupported claims, irreconcilable scenario/horizon defects, insufficient evidence coverage, or incoherent required fields. Block on leakage, tampering, or schema corruption. Do not repair by inventing values.

## Output contract

Return `ForecastVerification` with status, schema checks, evidence coverage, numeric/date checks, defects, forced-abstention reason, and exact bounded correction scope; never silently edit the forecast.

## Verification checklist

- Schema and bounds pass.
- Ticker, `as_of`, horizon, catalysts, and expiry align.
- Material claims and numbers trace to approved evidence.
- Scenario and abstention fields are coherent.
- No new facts, sizing, orders, risk changes, or promotion.

## Failure modes

Checking syntax but not entailment, tolerating unsupported precision, missing timezone/date errors, accepting contradictory abstention fields, silently repairing values, and approving self-referential evidence.

## Memory policy

No memory reads or writes. Verification cannot approve learning, promote the forecast, or modify future routing.

## Evaluation cases

Pass: fully traced coherent fixture. Bounded correction: non-material schema defect with no factual change. Forced abstention: unsupported material claim. Block: future evidence or malformed identity.

## Version history

`1.0.0` — Release-1 independent forecast audit.
