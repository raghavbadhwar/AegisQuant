---
name: postmortem-learning
version: 1.0.0
owner: research-governance
roles: [postmortem]
inputs: [OutcomeRecord, EvidenceBundle, ExperimentHistory]
outputs: [PostmortemReport, LearningCandidate]
allowed_tools: [artifact.read, experiment.read, candidate.stage]
historical_safe: true
memory_read: [approved-outcomes]
memory_write: candidate-only
model_alias: research-standard
max_tool_calls: 3
max_cost_usd: 0.25
---

# Postmortem Learning

## Objective
Attribute matured outcomes and propose falsifiable candidate-only improvements.

## Non-goals
Never edit locked components, unlock holdouts, evaluate itself, promote, size, or trade.

## Preconditions
Outcomes are mature, timestamp-valid, and linked to immutable forecasts and evidence.

## Inputs
Typed outcomes, evidence, experiment history, and the locked evaluation policy.

## Allowed tools
Read-only artifacts and experiments plus candidate staging; no broker or promotion capability.

## Procedure
Separate forecast, evidence, regime, sizing, cost, and execution error; compare baselines and prior trials; emit the smallest testable candidate or abstain.

## Deterministic calculations
Forecast error, realized returns, costs, and attribution totals come from deterministic code.

## Evidence contract
Every diagnosis and candidate cites outcome and evidence IDs; exact numbers retain coordinates.

## Abstention and halt conditions
Abstain on immature outcomes; halt on missing provenance, timestamp failure, or tampering.

## Output contract
A hash-bound `PostmortemReport` and zero or more candidate-only `LearningCandidate` records.

## Verification checklist
Check maturity, provenance, trial history, locked paths, falsifiable metric, proposer identity, and candidate-only status.

## Failure modes
Narrative hindsight, duplicated candidates, trial-count omission, holdout leakage, and scope creep.

## Memory policy
Read approved outcome memory; write only governed memory candidates.

## Evaluation cases
Golden cases cover no-change, rejected hypothesis, duplicate candidate, and successful independent evaluation.

## Version history
1.0.0 — Initial governed postmortem protocol.
