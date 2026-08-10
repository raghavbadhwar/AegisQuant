# Hermes Handoff — AegisQuant v3 / v4

You are taking over the AegisQuant institutional research and candidate world-model project. Work independently, make concrete code/test progress, and report only evidence-backed milestones. Do **not** wait for routine decisions. Preserve all safety/release gates.

## Canonical location

- Repository: `/Volumes/RAGHAV2/Development_Projects/AegisQuant`
- Compatibility path: `/Users/raghav/aegisquant-v3-institutional` (symlink)
- Branch: `upgrade/aegisquant-v3-institutional-os`
- Commit identity: obtain it from `git rev-parse HEAD`; this handoff deliberately
  does not hard-code a stale commit SHA.
- v4 design spec: `/Users/raghav/Downloads/AegisQuant_v4_Causal_World_Model_Design_Spec.md`

## Mandatory operating rules

1. One financial path only: historical work uses `backtest_fund()` → `run_cycle()`; never create a parallel order/risk/broker path.
2. No live trading, live broker, or autonomous capital deployment. Human promotion is mandatory.
3. Historical replay must be PIT: use `available_at <= as_of`, not a reporting-period proxy.
4. Never make performance, eligibility, investment, or release claims from synthetic, Yahoo, Stooq, or other non-release engineering data.
5. Preserve `aegis-cycle-v1` canonical/digest compatibility; institutional work uses v2 contracts.
6. Network is prohibited during historical replay. Capture source data first; replay from sealed local artifacts only.
7. Do not buy services, change credentials, publish, or send externally without approval. Routine local coding, free public-data engineering, tests, and local artifact generation are authorized.

## Current implemented state

### v3 institutional OS

- PIT SEC/XBRL/N-PORT ingestion, immutable raw artifacts, provenance hashes, availability gates, snapshots, and security-map verification are implemented.
- Post-remediation real SEC corpus: `data/pit/real-sec-v2` (local ignored); verified 2025 snapshot: 84 artifacts, 3 mappings, 248 N-PORT holdings.
- Pre-remediation `real-sec-sample` derived outputs are quarantined; retain bytes but do not use them as evidence.
- Receipt-only strategy evaluation with aligned interval-purged walk-forward/CPCV exists.
- Free engineering-only Yahoo fixture path exists:
  - Downloader: `aegis/data/yahoo_engineering.py`
  - Local data: `data/pit/yahoo-engineering-v3` (ignored)
  - Conservative next-UTC-day availability convention.
  - `apps/cli.py backtest --data-root ...` runs frozen local fixtures.
  - The local ignored replay ledger contains 366 `aegis-cycle-v1` records from
    `2019-01-05` through `2025-12-31`; it is plumbing evidence only and must not
    be used for release, performance, eligibility, investment, or governance claims.
  - Those records contain neither an institutional mandate nor a quant research
    bundle, so they cannot feed the receipt-only six-strategy comparison gates.
  - No local exact-cutoff historical-artifact manifest is present for
    `HistoricalMultiStrategyFixtureProvider`; do not synthesize one from the
    Yahoo fixture to bypass the institutional v2 requirement.

### v4 candidate-only OS

- Causal graph contracts and identification gates: `aegis/causal/contracts.py`
- Evidence-bound belief states: `aegis/causal/beliefs.py`
- Evidence-bound mechanism registry: `aegis/causal/mechanisms.py`
- PIT-bound world snapshots/interventions: `aegis/world_model/contracts.py`
- Deterministic candidate scenario propagation: `aegis/world_model/scenario.py`
- Domain-pack manifests and PIT-bound twins/transitions: `aegis/world_model/domain_pack.py`,
  `aegis/world_model/twin.py`
- Contribution reconciliation and single-linear experiment histories:
  `aegis/world_model/contributions.py`, `aegis/world_model/experiments.py`
- Candidate-only uncertainty/calibration declarations and counterfactual abstention:
  `aegis/world_model/uncertainty.py`, `aegis/world_model/counterfactual.py`
- Candidate-only research VOI contracts: `aegis/research_planner/`
- Engineering traceability projection and external original-seal receipt references:
  `aegis/reporting/traceability.py`, `docs/V4_TRACEABILITY.md`
- All 34 public v4 candidate Pydantic contracts use `CandidateContractModel`:
  frozen/`extra="forbid"` with revalidated, unknown-field-rejecting `model_copy()`.
- Content hashes are content addressing, not authentication. Traceability rendering
  requires a separately retained `TraceabilityReceiptReference` that binds the
  original report ID/hash.
- These modules have no execution, promotion, factual, pricing, portfolio, or
  release authority. Keep that boundary strict.

## Priority work

1. **v3 engineering closure:** use the local Yahoo engineering fixture to execute
   longer governed replays; produce receipts/ledgers and compare the six
   predeclared strategies through existing receipt/CPCV gates. Label every output
   `engineering-only/non-release`; do not state metrics as investment evidence.
2. Establish governed, externally retained receipt storage before treating any
   traceability projection as an original-record verification surface. The current
   projection records references only and cannot create or authorize that register.
3. Obtain approved release-grade source evidence to address the known blockers;
   do not convert engineering-only replay or traceability evidence into a release,
   performance, eligibility, investment, or governance claim.
4. Keep all v4 extensions candidate-only. Add focused tests first, then run Ruff,
   format, mypy, relevant tests, the full suite, and an independent read-only audit
   before substantive commits.

## Known release blockers — do not work around them

- No approved survivorship-safe PIT market/universe/corporate-action/delisting source exists. Thus real six-strategy performance qualification and release acceptance are blocked.
- Archived accession XBRL parsing replaces Company Facts in normalized ingestion; governed real-filing corpus and external original-record receipt evidence remain release-gated.
- Receipt-bound dated security-master import is implemented; an approved identifier-history source remains required for release-grade treatment.
- N-PORT archive-to-receipt, holding-identity, conservative observed-availability,
  and snapshot-source binding are implemented; governed historical dissemination
  evidence and externally retained original receipts remain release-gated.

## Validation commands

```bash
cd /Volumes/RAGHAV2/Development_Projects/AegisQuant
uv run ruff check aegis apps tests scripts/generate_demo_data.py
uv run ruff format --check aegis apps tests scripts/generate_demo_data.py
uv run mypy aegis apps
uv run pytest -q
uv lock --check
```

## Reporting format

At meaningful milestones, report: commit SHA; files/capability added; exact validation evidence; whether the result is `completed`, `engineering-only`, `release-gated`, or `deferred`; and remaining known risks. Do not send empty status updates.
