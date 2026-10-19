---
name: fundamental-quality-valuation
version: 1.0.0
owner: fundamental-research
roles:
- fundamentals
inputs:
- CaseContext
- FundamentalsSnapshot
- EvidenceBundle
outputs:
- FundamentalAssessment
allowed_tools:
- artifact.read
- data.financial_snapshot
- evidence.numeric_lookup
- calc.deterministic
historical_safe: true
memory_read: []
memory_write: none
model_alias: research-standard
max_tool_calls: 8
max_cost_usd: 0.5
---

## Objective

Assess business quality, profitability, balance-sheet resilience, valuation, management, and guidance from eligible point-in-time fundamentals.

## Non-goals

Do not fetch filings, fabricate estimates, silently mix periods or accounting bases, set price targets from unsupported assumptions, size positions, order trades, or promote changes. Explicit prohibition: do not size positions, construct or submit orders, introduce new facts, change hard risk, self-promote, or promote any skill, model, memory, strategy, or output.

## Preconditions

Require a ticker-matched financial snapshot, fiscal periods, currencies/units, filing availability timestamps, numeric provenance, and an eligible evidence bundle.

## Inputs

Distinguish reported, adjusted, derived, consensus, and scenario values. Treat management statements as attributed claims, not verified outcomes.

## Allowed tools

Use authorized artifact, snapshot, numeric lookup, and deterministic calculation tools only. No network, broker, risk, ledger, or memory-write access.

## Procedure

1. Validate entity, fiscal calendar, period, currency, units, and `available_at`.
2. Review revenue quality, margins, cash conversion, returns, reinvestment, dilution, leverage, and liquidity where supplied.
3. Separate recurring economics from one-offs and accounting adjustments.
4. Compare valuation on consistent numerator/denominator dates and bases.
5. Assess management/guidance only from eligible attributed evidence and prior results supplied.
6. State sensitivities, counterevidence, gaps, and uncertainty.

## Deterministic calculations

Recompute only supported ratios using point-in-time operands: growth, margins, free-cash-flow conversion, net leverage, per-share dilution, and valuation multiples. Record formula, operand IDs, dates, currency/units, and rounding; never fill missing operands.

## Evidence contract

Each material claim cites an `evidence_id`; each exact number also records field/table and filing/snapshot provenance. Revised data is usable only if its release was eligible at `as_of`.

## Abstention and halt conditions

Abstain or mark the affected dimension unavailable for entity/period mismatch, unresolvable units, missing denominator, stale/revised leakage, material reconciliation failure, or unsupported adjustments. Halt on provenance failure.

## Output contract

Return `FundamentalAssessment` with quality, profitability, balance sheet, valuation, management/guidance, sensitivities, counterevidence, uncertainties, evidence IDs, gaps, and abstention state.

## Verification checklist

- Entity, period, currency, and units align.
- Exact values have field/table provenance.
- Reported and adjusted values are labeled.
- Ratios reconcile to cited operands.
- No unsupported price target, sizing, order, new fact, or promotion.

## Failure modes

Period mixing, denominator drift, stale shares, currency mismatch, capitalizing one-offs, using later restatements, double-counting cash/debt, and treating guidance as fact.

## Memory policy

No memory reads or writes in Release 1. Do not turn management impressions or valuation conclusions into durable memory.

## Evaluation cases

Pass: complete filing fixture produces traceable ratios and sensitivities. Partial abstention: valuation denominator absent. Block: a restatement released after `as_of` enters the snapshot.

## Version history

`1.0.0` — Release-1 replay-safe fundamental quality and valuation procedure.
