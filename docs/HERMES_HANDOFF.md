# Hermes Handoff — AegisQuant v3 / v4

You are taking over the AegisQuant institutional research and candidate world-model project. Work independently, make concrete code/test progress, and report only evidence-backed milestones. Do **not** wait for routine decisions. Preserve all safety/release gates.

## Canonical location

- Repository: `/Volumes/RAGHAV2/Development_Projects/AegisQuant`
- Compatibility path: `/Users/raghav/aegisquant-v3-institutional` (symlink)
- Branch: `upgrade/aegisquant-v3-institutional-os`
- Current HEAD: `578f7a48c5d2fb3c4b965cdb2b2ae820e3a8a053`
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
  - 13-cycle engineering smoke backtest completed without displaying performance metrics.

### v4 candidate-only OS

- Causal graph contracts and identification gates: `aegis/causal/contracts.py`
- Evidence-bound belief states: `aegis/causal/beliefs.py`
- Evidence-bound mechanism registry: `aegis/causal/mechanisms.py`
- PIT-bound world snapshots/interventions: `aegis/world_model/contracts.py`
- Deterministic candidate scenario propagation: `aegis/world_model/scenario.py`
- These modules have no execution, promotion, factual, pricing, or portfolio authority. Keep that boundary strict.

## Priority work

1. **v3 engineering closure:** use the local Yahoo engineering fixture to execute longer governed replays; produce receipts/ledgers and compare the six predeclared strategies through existing receipt/CPCV gates. Label every output `engineering-only/non-release`; do not state metrics as investment evidence.
2. Add traceability/report artifacts for source provenance, snapshot hashes, run ledgers, receipt comparison, and explicit release disposition.
3. **v4B–v4D:** implement deterministic, domain-bounded twin/domain-pack contracts; scenario compiler; contribution ledger; uncertainty/sensitivity; calibration/validation and experiment ledger; counterfactual/VOI contracts. All outputs stay candidate-only until v3 acceptance.
4. Add focused tests first, then run Ruff, format, mypy, relevant tests, and full suite before substantive commits.
5. Seek an independent read-only audit after meaningful closure.

## Known release blockers — do not work around them

- No approved survivorship-safe PIT market/universe/corporate-action/delisting source exists. Thus real six-strategy performance qualification and release acceptance are blocked.
- SEC Company Facts current API provenance has limitations for production historical revisions; archived accession XBRL parsing is the eventual standard.
- Security-master ticker history needs a dated identifier-history source for release-grade treatment.
- N-PORT disclosure timing and raw archive-to-receipt binding need further production hardening.

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
