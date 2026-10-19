---
name: cio-synthesis
version: 1.0.0
owner: investment-judgment
roles:
- cio
inputs:
- CaseContext
- ApprovedResearchArtifacts
- EvidenceAudit
- BullMemo
- BearMemo
- BaseRateMemo
outputs:
- AlphaForecast
allowed_tools:
- artifact.read
historical_safe: true
memory_read: []
memory_write: none
model_alias: judge-high
max_tool_calls: 2
max_cost_usd: 0.35
---

## Objective

Synthesize approved research into a calibrated, evidence-linked `AlphaForecast` or an explicit abstention.

## Non-goals

Do not retrieve or add facts, reopen quarantined evidence, redo specialist research, hide disagreement, size a portfolio, submit an order, alter risk, or promote any component. Explicit prohibition: do not size positions, construct or submit orders, introduce new facts, change hard risk, self-promote, or promote any skill, model, memory, strategy, or output.

## Preconditions

Require schema-valid case context, a passing/non-blocking Evidence Audit, approved artifact manifest, independent Bull/Bear attestations, base-rate memo, and horizon.

## Inputs

Only artifacts on the Auditor-approved manifest may inform synthesis. Unresolved contradictions, missing dimensions, and confidence limits remain visible.

## Allowed tools

Read only approved artifacts. No evidence search, network, calculator, data, broker, risk, ledger, or memory tools; tool absence prevents introducing new facts.

## Procedure

1. Validate gates, manifest, horizon, and Bull/Bear independence.
2. Summarize specialist contributions and unresolved contradictions without changing facts.
3. Anchor on the base rate, then explain evidence-backed case-specific updates.
4. Select already validated downside/base/upside values or leave unsupported numeric fields null.
5. Set probability positive, confidence, uncertainty, catalysts, invalidations, and expiry coherently.
6. Emit `AlphaForecast` or explicit abstention and record the synthesis trace.

## Deterministic calculations

Perform no new financial calculations. Use only validated numeric fields from approved artifacts. Check required bounds and scenario ordering logically; unsupported expected return or volatility stays null rather than being invented.

## Evidence contract

Every material thesis sentence, component, scenario, catalyst, and invalidation cites approved evidence IDs. Synthesis may combine supported premises but must label inference and cannot create a new factual premise.

## Abstention and halt conditions

Abstain if the audit blocks, material claims lack coverage, scenario ordering cannot be made coherent, horizon conflicts remain, required independence failed, or evidence is too weak for calibrated judgment.

## Output contract

Return the v2 `AlphaForecast` fields, including evidence IDs, invalidations, catalysts, expiry, components, confidence/uncertainty, and abstention fields, plus an artifact-level synthesis trace.

## Verification checklist

- All prerequisite gates and manifests pass.
- No new evidence or facts introduced.
- Scenario order and probability/confidence bounds are coherent.
- Disagreement and null fields remain visible.
- No sizing, orders, broker/ledger action, risk change, or promotion.

## Failure modes

Averaging incompatible views, false numeric precision, confidence unsupported by coverage, ignoring base rates, citation laundering, hidden nulls, and turning inference into fact.

## Memory policy

No memory reads or writes. The forecast is a case artifact, not a durable lesson or self-approved strategy change.

## Evaluation cases

Pass: coherent audited dossier produces fully traced forecast. Abstain: audit block, scenario incoherence, or missing material coverage. Fail: any uncited new fact appears.

## Version history

`1.0.0` — Release-1 evidence-bounded CIO synthesis.
