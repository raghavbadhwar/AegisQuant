---
name: base-rate-analysis
version: 1.0.0
owner: investment-review
roles:
- base-rate
inputs:
- CaseContext
- BaseRateSnapshot
- CohortDefinition
outputs:
- BaseRateMemo
allowed_tools:
- artifact.read
- data.base_rate_snapshot
- calc.deterministic
historical_safe: true
memory_read: []
memory_write: none
model_alias: research-standard
max_tool_calls: 4
max_cost_usd: 0.25
---

## Objective

Produce a leakage-safe empirical prior from a frozen, comparable historical cohort, with denominators, distributions, and limitations visible.

## Non-goals

Do not cherry-pick analogues, search for a preferred precedent, use future outcomes, claim causality, override case evidence, size positions, place orders, or promote findings. Explicit prohibition: do not size positions, construct or submit orders, introduce new facts, change hard risk, self-promote, or promote any skill, model, memory, strategy, or output.

## Preconditions

Require an explicit event/outcome definition, cohort rules, observation and forecast horizons, frozen records, availability timestamps, censoring policy, and minimum sample rule.

## Inputs

Treat cohort construction metadata and records as authoritative. Keep empirical prior separate from case-specific posterior judgment.

## Allowed tools

Read authorized frozen base-rate artifacts and use deterministic calculations only. No network, live retrieval, broker, risk, ledger, or memory-write tools.

## Procedure

1. Validate cohort inclusion/exclusion before viewing outcomes.
2. Enforce information and outcome cutoffs relative to each historical anchor and the case `as_of`.
3. Check sample size, duplicates, missingness, censoring, survivorship, regime mix, and comparability.
4. Compute declared distributions/frequencies with denominators and uncertainty.
5. Describe case-to-cohort similarities and differences without changing membership post hoc.
6. Return a prior range or insufficient-data result.

## Deterministic calculations

From frozen records compute `n`, event frequency `k/n`, mean, median, declared quantiles, dispersion, and confidence interval using the specified method. Record exclusions and denominator changes; never impute outcomes unless policy explicitly supplies the method.

## Evidence contract

Every cohort record and aggregate traces to snapshot IDs and frozen rules. Eligibility uses information available by each anchor; later outcomes are used only when legitimately matured and recorded by the replay fixture.

## Abstention and halt conditions

Return `insufficient-data` for samples below the declared minimum, material censoring, unstable definitions, outcome leakage, or poor comparability. Halt when cohort rules changed after outcome inspection.

## Output contract

Return `BaseRateMemo` with cohort definition, dates/horizon, `n`, exclusions, distributions/frequencies, uncertainty interval, regime mix, comparability, biases, prior range, evidence IDs, and status.

## Verification checklist

- Cohort rules predate outcome review.
- Denominators and exclusions reconcile.
- Censoring and survivorship assessed.
- Prior remains distinct from case conclusion.
- No future leakage, cherry-picking, sizing, orders, or promotion.

## Failure modes

Analogue cherry-picking, tiny samples, overlapping observations, hindsight-defined cohorts, survivorship, regime mismatch, censored losers, and false precision.

## Memory policy

No memory reads or writes. Use only the frozen base-rate snapshot; a result cannot become a durable rule without later governed evaluation.

## Evaluation cases

Pass: adequate frozen cohort yields reproducible distribution. Insufficient: sample below minimum. Block: cohort membership or outcome availability uses future information.

## Version history

`1.0.0` — Release-1 replay-safe base-rate analysis.
