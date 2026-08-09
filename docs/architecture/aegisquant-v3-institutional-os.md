# AegisQuant v3 Institutional Investment OS — Architecture

## Authority and release basis

The authoritative inputs are `docs/specs/AegisQuant_v3_Institutional_Investment_OS_Spec.md` and `docs/specs/AegisQuant_v3_Institutional_Codex_Master_Prompt.md`. v3 starts from audited v2 commit `8cce4d5`; every v2 safety and reproducibility invariant remains a release gate.

## Product boundary

AegisQuant is a local-first, evidence-first institutional research and simulated fund operating system. Company and strategy research are first-class and may run without a fund. Agents may propose assumptions and interpretations. Only deterministic code may normalise statements, calculate metrics, forecast statements, value securities, blend forecasts, construct/net portfolios, enforce risk, simulate orders, reconcile ledgers, evaluate candidates, or activate promotions. There is no live-money broker.

## Capability flow

```text
Research request / monitored event
  -> entity + PIT evidence snapshot
  -> raw filing facts (immutable)
  -> reversible statement normalisation + lineage
  -> archetype router
  -> deterministic metrics / forecasts / valuation
  -> bounded specialist interpretations
  -> evidence + calculation audit
  -> living thesis + fundamental scorecard
  -> standard AlphaForecast

Universe PIT snapshot
  -> lagged factor/event/regime features
  -> diagnostics + honest validation
  -> alpha forecasts

AlphaForecasts
  -> forecast blender
  -> strategy pod policies + risk budgets
  -> fund allocator
  -> net master target
  -> existing deterministic portfolio/risk/order/run_cycle path
  -> replay / backtest / recommendation / persistent paper book
  -> outcomes, thesis checkpoints, memory, candidate-only learning
```

## Module ownership

- `aegis/contracts/`: versioned serialisable domain contracts; no business calculations.
- `aegis/fundamentals/`: filings, normalisation, archetypes, metrics, operating forecasts, valuation, management, thesis and dossiers.
- `aegis/quant_research/`: PIT universe, factors, events, regimes, diagnostics and model comparison.
- `aegis/strategy/`: alpha-model protocol, blending, pods, allocator, netting and attribution.
- `aegis/paper/`: exchange sessions, persistent simulated book, idempotent scheduler, restart/reconciliation and event triggers.
- Existing `aegis/fund/run_cycle.py`, risk, broker and cycle ledger remain the sole financial-cycle authority.
- Existing source, evidence, memory and research-lab stores remain authoritative; v3 adds typed records rather than parallel control planes.
- `apps/cli.py` and `apps/dashboard.py` are control/observation surfaces and may not bypass services.

## Data and time invariants

Every persisted fact has `available_at`; filing facts also preserve period, accepted timestamp, accession, form, unit and raw coordinate. Historical selection is `available_at <= as_of`. Normalised values never overwrite facts. Every adjustment is reversible, linked to facts, and hash-bound. Restatements are separate revisions. Universe membership, factor observations, guidance, theses, memory and outcomes obey the same cutoff.

## Calculation authority

Persisted calculation records identify calculator/version, typed inputs, source evidence/facts, output, units and content hash. LLM/model text cannot be a calculation source. Forecast assumptions may be proposed by agents but typed engines create statements and values. DCF, reverse DCF, comps, scenarios, factor diagnostics, event CARs, forecast blending, portfolio models and attribution are deterministic.

## Research graphs

The v3 fundamental graph ends at `FundamentalResearchDossier` and `AlphaForecast`. The thesis committee sees only audited evidence and calculations and has no source capability. Quant models also end at standard forecasts. Neither graph can size, risk-check or trade.

## Multi-strategy hierarchy

`FundMandate -> StrategyPod -> AlphaModel -> ForecastBlender -> PodPortfolioPolicy -> PodTarget -> FundAllocator -> MasterTarget -> existing master risk/run_cycle`. Initial pods are fundamental expectations, earnings/events, systematic quality-momentum and defensive regime overlay. Pod contributions are preserved through netting.

## Paper operations

Paper mode persists a simulated book and cycle keys, uses exchange sessions, and delegates every target to the same existing deterministic sizing/risk/order/fill/reconciliation path. Restart restores receipts and reconciles before another cycle. Duplicate cycle keys cannot create orders. Monitors can create cases, never orders.

## Learning and promotion

Forecast outcomes attribute thesis, fundamentals, valuation, factor/beta, timing, sizing, costs, risk interventions and shocks. Candidates remain overlays. Champion/challenger shadow output cannot affect weights. Promotion and rollback require independently evaluated, hash-bound, append-only human events; broker and risk-relaxation changes are forbidden.

## Dependency rule

The deterministic fallback is authoritative. Optional libraries (`statsmodels`, `skfolio`, `exchange_calendars`, controlled source/memory adapters) live behind typed adapters with licence notes, pinned versions, equivalence/failure tests and no replay dependency.

## Release sequence

v3A fundamental intelligence -> v3B quant/multi-strategy -> v3C monitoring/paper -> v3D memory/learning. A later phase may start only with the prior phase tests green. `docs/V3_TRACEABILITY.md` binds every criterion to code and tests.
