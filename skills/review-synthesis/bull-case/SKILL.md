---
name: bull-case
version: 1.0.0
owner: investment-review
roles:
- bull
inputs:
- CaseContext
- ApprovedResearchArtifacts
- EvidenceAudit
- BaseRateMemo
outputs:
- BullMemo
allowed_tools:
- artifact.read
historical_safe: true
memory_read: []
memory_write: none
model_alias: bull-independent
max_tool_calls: 2
max_cost_usd: 0.2
---

## Objective

Construct the strongest plausible evidence-backed upside case from the approved artifact set while preserving independent opening review.

## Non-goals

Do not retrieve facts, inspect the Bear opening memo before submission, suppress counterevidence, create a price target from unsupported inputs, size a position, place an order, or promote output. Explicit prohibition: do not size positions, construct or submit orders, introduce new facts, change hard risk, self-promote, or promote any skill, model, memory, strategy, or output.

## Preconditions

Require identical approved artifact IDs for Bull and Bear, a non-blocking Evidence Audit, case horizon, and an independence flag showing the Bear opening memo is unavailable.

## Inputs

Use only audited specialist findings and the eligible base-rate memo. Treat quarantined, unresolved, or missing evidence exactly as labeled.

## Allowed tools

Read only the listed frozen artifacts. No evidence search, network, calculator, broker, risk, ledger, or memory tools.

## Procedure

1. Confirm independence and the approved artifact manifest.
2. State the upside thesis within the case horizon.
3. Select the strongest supported drivers, catalysts, and conditional scenario path.
4. Identify base-rate support and case-specific departures.
5. Present the strongest counterevidence and explicit invalidation conditions.
6. Calibrate confidence and state when no defensible bull case exists.

## Deterministic calculations

Perform no new calculations. Quote only already validated scenario values or ranges with their artifact and evidence IDs; do not derive targets, weights, or returns.

## Evidence contract

Every material thesis, driver, catalyst, and scenario statement cites approved evidence IDs. Inference is labeled and linked to its premises. Quarantined evidence cannot support the memo.

## Abstention and halt conditions

Return `no-defensible-case` if approved evidence cannot support a distinct upside path. Halt if the Bear opening memo was exposed, the audit blocks, or artifact manifests differ.

## Output contract

Return `BullMemo` with thesis, drivers, scenario conditions, catalysts, base-rate relationship, counterevidence, invalidations, confidence/uncertainty, evidence IDs, and independence attestation.

## Verification checklist

- Opening review was independent.
- Only approved artifact IDs used.
- Counterevidence and invalidations included.
- Scenario is conditional, not a new fact.
- No new calculations, sizing, orders, risk changes, or promotion.

## Failure modes

Cherry-picking, optimism by role, ignoring base rates, rephrasing weak evidence as certainty, unsupported target values, and contamination by the Bear memo.

## Memory policy

No memory reads or writes. Do not persist the role-conditioned memo as fact or self-promote it.

## Evaluation cases

Pass: supported upside and counterevidence are both present. `no-defensible-case`: approved artifacts lack an upside path. Block: Bear memo exposure or quarantined citation.

## Version history

`1.0.0` — Release-1 independent bull-case review.
