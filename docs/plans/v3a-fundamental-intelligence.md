# v3A — Fundamental Intelligence & Valuation Plan

## Deliverables
1. Versioned contracts for research requests, archetypes, filing facts/snapshots, normalised statements, adjustments/lineage, metrics, specialist assessments, drivers/forecasts, valuations, management, thesis/checkpoints, scorecard and dossier.
2. Immutable raw filing fixture/store seam retaining SEC-style timestamps/accessions/coordinates and restatement revisions.
3. Deterministic general-company normaliser with reported/adjusted views, reversible adjustments, statement reconciliation and explicit unsupported-archetype abstention.
4. Deterministic metrics for growth, margins, returns, reinvestment, cash/accounting quality, leverage/liquidity, dilution/capital allocation and per-share creation.
5. Three-scenario driver forecast with statement arithmetic and ordering gates.
6. FCFF DCF, reverse-DCF root solving, comparable distributions, scenario valuation, sensitivity grids and SOTP interface/abstention.
7. Management/guidance comparisons and immutable thesis ledger.
8. Fundamental service/graph producing calculation-audited JSON/Markdown dossier and standard AlphaForecast.
9. Markdown policies, agent manifests and skills referencing tested tools.
10. Frozen golden fixtures: compounder, expensive growth, cyclical, accounting warning, unsupported bank, guidance deterioration, acquisition-heavy and abstention.

## Gate tests
PIT/restatement/lineage; statement identities; reversible adjustments; metrics identities; forecast reconciliation/order; DCF golden/cross-check/round-trip/monotonicity; reverse-DCF recovery/feasibility; unsupported abstention; exact-number calculation linkage; graph authority/evidence confinement; byte-stable dossier and CLI.

## Implementation result

Status: **IN PROGRESS / RELEASE BLOCKED** pending a frozen-tree independent audit. Local implementation gates are green; unsupported archetypes and SOTP limitations remain explicit abstentions. The current local full-suite baseline is Ruff, strict mypy, and 119 pytest cases, but local gates do not override an independent finding.
