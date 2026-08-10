# AegisQuant v4 Traceability and Release Disposition

## Current disposition

**`release-gated` / `engineering-only` — not release accepted.**

The v4 world-model modules provide candidate-only contracts for causal graphs,
world snapshots, scenarios, twins, uncertainty, experiments, contributions,
counterfactual abstentions, and research value-of-information. They do not
provide broker, order, portfolio, pricing, factual, promotion, or release
authority.

The v4D investor-response and portfolio-scenario contracts are likewise
candidate-only. Their response provenance is always `not_calibrated`; their
portfolio linkage accepts only hash-only v3 engineering run-receipt references;
and their reports contain candidate impact/exposure units, never weights,
orders, risk decisions, approvals, or promotion output. Event calibration,
baseline comparison, and any outperformance assertion remain release-gated
until governed survivorship-safe PIT evidence and retained receipts exist.

The v4E microstructure module is an isolated engineering-only stress adapter.
It retains the fixed `aegis-v3-simulated-execution-cost-seam` boundary label but
does not import or invoke the v3 broker/execution path and accepts no order
inputs. ABIDES, StockSim, and DeepMarket are represented only by explicit
`integration_not_approved` abstentions until their dependencies, licences, and
separate validation are approved.

`aegis.reporting.traceability.EngineeringTraceabilityReport` is the governed,
read-only projection for the engineering evidence that accompanies this work.
It records hash references only; it neither reads external sources nor emits a
performance claim.

## Projection bindings

| Required reference | Projection field | Gate |
|---|---|---|
| Public source artifact | `source_provenance` | Unique source IDs; `available_at <= as_of` |
| PIT world/data snapshot | `snapshots` | Unique snapshot IDs; snapshot cutoff cannot exceed report cutoff |
| Governed engineering replay receipt | `run_ledger_receipts` | Unique run IDs; every receipt snapshot hash must appear in `snapshots` |
| Six-way comparison declaration | `strategy_comparison` | Exactly the six predeclared strategy IDs; readiness is not a performance result |
| Release state | `release_disposition`, `release_eligible`, `release_blockers` | Only `engineering_only` or `release_gated`; `release_eligible` is permanently `false` |
| Original projection seal | separately retained `TraceabilityReceiptReference` | `report_id` and original `report_content_hash` must match before rendering |

The projection is frozen, `extra="forbid"`, deterministically SHA-256 sealed,
and every public `model_copy()` update is reconstructed through Pydantic
validation. A SHA-256 content hash is not an authenticated signature: a
validator-valid replacement can calculate its own hash. Therefore
`verified()` and `traceability_view()` require a `TraceabilityReceiptReference`
retrieved from a separately retained, append-only governed receipt register.
They reject any report ID or content hash that does not match that original
receipt. The projection itself does not read, write, or authorize that register.

## Current release blockers

1. There is no approved survivorship-safe, PIT market/universe/corporate-action/delisting source.
2. Archived accession XBRL parsing is implemented, but a governed real-filing corpus and externally retained original-record receipts remain unavailable.
3. Security-master ticker history needs a dated identifier-history source.
4. N-PORT disclosure timing and raw archive-to-receipt binding need production hardening.

The local Yahoo fixture and all reports bound to it are engineering-only
plumbing evidence. They cannot support release acceptance, eligibility,
performance, investment, or governance claims.

## Verification

- `tests/unit/test_world_model_traceability.py` verifies candidate-only,
  release-gated rendering; sealed hash binding; direct model-copy validation;
  and rejection of a validator-valid replacement whose recomputed hash does
  not match the separately retained original receipt.
- `tests/world_model/`, `tests/causal/`, and `tests/research_planner/` cover
  the linked v4 contracts.
- Release remains subject to the complete gates in `docs/HERMES_HANDOFF.md`
  and is never changed by this document or projection.
