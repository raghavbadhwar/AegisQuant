---
name: case-plan
version: 1.0.0
owner: research-orchestration
roles:
- coordinator
inputs:
- CaseContext
- CapabilityManifest
- CaseBudget
- FixtureIndex
outputs:
- CasePlan
allowed_tools:
- artifact.read
- artifact.write
- budget.read
historical_safe: true
memory_read: []
memory_write: none
model_alias: research-standard
max_tool_calls: 6
max_cost_usd: 0.25
---

## Objective

Produce the smallest sufficient, replay-safe research plan with explicit tasks, skill versions, budgets, dependencies, audit gates, and completion criteria.

## Non-goals

Do not analyze the security, form a final forecast, retrieve new facts, size positions, create orders, alter risk, or promote any change. Explicit prohibition: do not size positions, construct or submit orders, introduce new facts, change hard risk, self-promote, or promote any skill, model, memory, strategy, or output.

## Preconditions

Require a schema-valid case identifier, ticker, `as_of`, horizon, mode, capability manifest, fixture index, and hard case budget.

## Inputs

Treat `CaseContext` and capabilities as authoritative. Treat missing fixtures, unavailable skills, and budget ceilings as constraints, not invitations to improvise.

## Allowed tools

Use only frontmatter-listed artifact and budget operations authorized by the capability broker. Replay and historical plans are network-denied.

## Procedure

1. Validate identity, ticker, mode, `as_of`, horizon, and requested deliverable.
2. Inventory eligible fixture artifacts and required gates.
3. Choose L0 screen, L1 standard, L2 event, or L3 deep; use the lowest depth that answers the case.
4. Assign typed tasks, pinned skill versions, independence rules, dependencies, per-task budgets, and completion criteria.
5. Require Evidence Auditor before debate/synthesis and Forecast Verifier after CIO.
6. Record unresolved questions, one permitted retry where applicable, and halt conditions.

## Deterministic calculations

Deterministically verify that the sum of task call and cost caps does not exceed the supplied case budget. Depth selection is rule-based from case type and fixture availability; it is not a return forecast.

## Evidence contract

The plan must identify required evidence classes and point-in-time eligibility. It must not make security claims. Every referenced artifact uses its existing ID; no citation or fact may be invented.

## Abstention and halt conditions

Halt on invalid case identity, missing `as_of`, inconsistent mode, capability-policy conflict, or budget overflow. Return `unplannable` when required artifacts or roles are unavailable.

## Output contract

Return one `CasePlan`: plan ID, case ID, depth, ordered tasks, role/skill/version, dependencies, budgets, required inputs/outputs, audit gates, independence constraints, retry limit, unresolved questions, and status.

## Verification checklist

- Required context fields validated.
- Historical/replay network denial preserved.
- Total budgets within cap.
- Bull/Bear opening independence preserved.
- Auditor and Verifier gates present.
- No forecast, sizing, order, or promotion content.

## Failure modes

Over-scoping wastes budget; under-scoping misses a material event; hidden dependencies break replay; vague completion criteria permit unsupported synthesis. Surface each explicitly.

## Memory policy

No memory reads or writes in Release 1. Use only frozen case artifacts. Any future learning output must be candidate-only and outside this procedure.

## Evaluation cases

Pass: a standard replay case yields an L1 plan within budget. Pass: an event fixture yields L2 with independent Bull/Bear. Fail closed: missing `as_of`, required fixture, or audit capability.

## Version history

`1.0.0` — Release-1 replay-safe planning procedure.
