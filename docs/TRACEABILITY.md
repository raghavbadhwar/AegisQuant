# Acceptance Traceability

Authoritative criteria are in `docs/BUILD_SPEC.md`. Status values are `PASS`, `IN PROGRESS`, or `PLANNED`; only deterministic evidence from the named test/command can move a gate to PASS.

## Release 0 — deterministic spine

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| Fresh clone/no-key replay | `apps/cli.py`, fixture providers | `tests/acceptance/test_cli_demo.py::test_no_key_replay_is_offline_and_byte_stable` | PASS |
| Point-in-time fixture filtering | `aegis/data/fixtures.py` | `tests/unit/test_data_fixtures.py` | PASS |
| Evidence-linked forecasts | `aegis/contracts/{evidence,forecasts}.py`, fixture provider | `tests/unit/test_contracts.py`, `tests/integration/test_replay_cycle.py` | PASS |
| Model abstention/data halt | contracts, `run_cycle` | `test_all_model_abstentions_hold_existing_book`, data integrity tests | PASS |
| Deterministic construction/risk | `aegis/quant/portfolio.py`, `aegis/risk/checks.py` | `tests/unit/test_portfolio_risk.py` | PASS |
| Simulated reconciliation | `aegis/brokers/simulated.py`, cycle receipt | broker tests and replay integration | PASS |
| Same historical/paper financial path | `aegis/fund/backtest.py` calls `run_cycle` | `tests/backtest/test_same_cycle_path.py` | PASS |
| Reproducibility manifest | `aegis/observability/manifests.py` | replay receipt assertions | PASS |
| Tamper-evident ledger | `aegis/fund/ledger.py` | `test_ledger_tamper_is_detected` | PASS |
| Unit/lint/type gates | pyproject/CI | `pytest`, `ruff`, `mypy` | PASS |

## Release 1 — replayable agent desk

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| Versioned Markdown skills | `skills/**`, `aegis/harness/skill_loader.py` | `tests/unit/test_harness.py` | PASS |
| Runtime capabilities and budgets | `capability_broker.py`, `budgets.py` | harness and security tests | PASS |
| Deterministic parallel LangGraph desk | `aegis/harness/{state,graph}.py` | `tests/integration/test_graph_replay.py` | PASS |
| Independent Bull/Bear/Base-Rate | graph join and opening input hash | graph independence test | PASS |
| CIO evidence confinement | artifact evidence allowlist | adversarial rogue-evidence test | PASS |
| Verifier/model-failure abstention | verifier/CIO branches | injected role-failure tests | PASS |
| Full dossier/replay determinism | `ResearchDossier`, canonical reducers | CLI byte comparison and graph determinism | PASS |

## Release 2 — source intelligence and evidence

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| Raw-first mode-gated gateway | `aegis/sources/{planner,pipeline,raw_store}.py` | source integration/security tests | PASS |
| Typed Agent Reach/Scrapling boundaries | `aegis/sources/adapters.py` | contract/security tests | PASS |
| Safe normalization/injection scan | `normalizer.py` | malicious-source integration test | PASS |
| Claim graph and deterministic audit | `aegis/evidence/**` | source + graph integration tests | PASS |
| Health and one-shot watchers | `health.py`, `watchers.py` | unit contracts and deterministic functions | PASS |

## Release 3 — governed memory

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| Candidate/governance append-only store | `aegis/memory/local_backend.py` | `tests/memory` | PASS |
| PIT/status/expiry retrieval | local backend + graph context | memory and graph tests | PASS |
| Contradiction visibility/snapshot hash | memory hits/snapshots | memory tests | PASS |
| Failure-safe GBrain projection boundary | `gbrain_adapter.py` | outage/future-ID test | PASS |

## Release 4 — validation and improvement

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| Locked candidate surfaces | `research_lab/boundaries.py` | traversal/symlink tests | PASS |
| qtype first + built-in checker | pinned optional qtype, `static_checks.py` | qtype golden test | PASS |
| Purged WF/CPCV/PBO/PSR/DSR | `validation.py`, optional purgedcv | lab golden tests | PASS |
| Immutable experiments | `experiments.py` | tamper/idempotency test | PASS |
| Independent evaluation/human promotion | `promotion.py` | hash/separation tests | PASS |

## Release 5 — presentation and robustness

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| Read-only complete audit dashboard | `apps/dashboard.py`, `aegis/reporting/**` | dashboard + reader tests | PASS |
| Operations/architecture/release docs | `docs/{ARCHITECTURE,DASHBOARD,OPERATIONS,RELEASE_CHECKLIST}.md` | documented command smoke tests | PASS |
| Full frozen CI gates | `.github/workflows/ci.yml` | Ruff/mypy/pytest/replay cmp | PASS |

## Capability-complete criteria

| Spec AC | Short name | Target release | Status |
|---:|---|---:|---|
| 1 | no-key replay | 0 | PASS |
| 2 | historical live-source/future-memory denial | 1/3 | PASS |
| 3 | raw-before-interpretation | 2 | PASS |
| 4 | typed Agent Reach/Scrapling wrappers | 2 | PASS |
| 5 | Scrapling allowlists/limits/mode | 2 | PASS |
| 6 | material-claim provenance | 1/2 | PASS |
| 7 | numeric coordinates/calculations | 1/2 | PASS |
| 8 | injection flagged/not obeyed | 2 | PASS |
| 9 | source/parser versions | 0/2 | PASS |
| 10 | GBrain failure-safe replay | 3 | PASS |
| 11 | governed memory candidates | 3 | PASS |
| 12 | contradictory/superseded memory visible | 3 | PASS |
| 13 | PIT-safe memory retrieval | 3 | PASS |
| 14 | independent Bull/Bear openings | 1 | PASS |
| 15 | CIO synthesis confinement | 1 | PASS |
| 16 | verifier-forced abstention | 1 | PASS |
| 17 | LLM abstain/held-price halt | 0/1 | PASS |
| 18 | deterministic construction | 0 | PASS |
| 19 | deterministic auditable risk | 0 | PASS |
| 20 | order/cash/position/NAV reconciliation | 0 | PASS |
| 21 | one financial cycle | 0 | PASS |
| 22 | immutable experiment history | 4 | PASS |
| 23 | locked candidate boundary | 4 | PASS |
| 24 | qtype/time checks first | 4 | PASS |
| 25 | baselines/ablations/PBO/DSR/cost/drawdown | 4 | PASS |
| 26 | staged candidate diffs | 4 | PASS |
| 27 | proposer/evaluator separation | 4 | PASS |
| 28 | no pre-promotion portfolio effect | 4 | PASS |
| 29 | case reproducibility manifest | 0 | PASS |
| 30 | golden replay/scraping CI fixtures | 0/2 | PASS |
