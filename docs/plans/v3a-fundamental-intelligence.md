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

Status: **PASS** at capability commit `24eabc9d6cd6690334eba8572115b46f7703e546` (tree `02e97672a412f12e87dbf9baeea1d364b9557d2b`), independently verified with P0=0, P1=0, P2=0 and a clean committed worktree. The accepted baseline is Ruff format/check, strict mypy over 97 source files, 130 tests, deterministic replay/company outputs, and explicit unsupported-archetype/SOTP abstentions. v3B may begin only from this boundary without weakening v2/v3A invariants.
