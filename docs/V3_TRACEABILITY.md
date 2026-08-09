# AegisQuant v3 Traceability

Authoritative inputs: `docs/specs/AegisQuant_v3_Institutional_Investment_OS_Spec.md` and `docs/specs/AegisQuant_v3_Institutional_Codex_Master_Prompt.md`.

Status is `PLANNED`, `IN PROGRESS`, or `PASS`; only named deterministic tests may move a criterion to PASS.

| # | Final acceptance criterion | Verification | Status |
|---|---|---|---|
| 1 | Company research independent of fund | `test_company_research_cli_is_fund_independent_and_replay_safe`, `test_public_api_and_verified_forecast_enforce_committee_authority` | PASS |
| 2 | Deterministic calculations and evidence lineage | `test_exact_statement_numbers_reversible_adjustments_and_closed_lineage`, `test_scorecard_fields_match_same_named_calculation_lineage`, `test_future_nonfiling_inputs_and_dimension_corruption_halt` | PASS |
| 3 | DCF/reverse DCF assumptions, ranges, sensitivities | `test_dcf_golden_cross_check_and_monotonicity`, `test_reverse_dcf_round_trip_and_no_root_are_explicit`, `test_dcf_sensitivity_cells_have_dependency_complete_exact_lineage` | PASS |
| 4 | Agents use verified calculations | `test_graph_rejects_missing_specialist_and_evidence_widening`, `test_specialist_conclusions_are_calculation_first_and_all_abstain_is_typed`, `test_approved_graph_computes_numeric_core_once` | PASS |
| 5 | Personas optional, not voters | `test_fundamental_graph_is_deterministic_and_binds_driver_proposer`; specialist roles contain no persona/voting path | PASS |
| 6 | Backtestable calibrated fundamental forecast | `test_all_golden_cases_are_deterministic_and_safely_routed`, `test_public_api_and_verified_forecast_enforce_committee_authority`; typed committee-bound forecast | PASS |
| 7 | Factor/event/regime/portfolio evaluation | v3B diagnostics tests | PLANNED |
| 8 | Visible competitive simple baselines | model comparison tests | PLANNED |
| 9 | Pods net to deterministic fund book | pod netting/attribution tests | PLANNED |
| 10 | Replay/backtest/current/paper coherence | cross-mode acceptance | PLANNED |
| 11 | Historical evidence/memory PIT | temporal adversarial tests | PLANNED |
| 12 | Every candidate recorded/evaluated | experiment-ledger tests | PLANNED |
| 13 | No candidate self-promotion | promotion adversarial tests | PLANNED |
| 14 | All v2/v3 tests pass | full CI gates | PLANNED |
| 15 | Two isolated replay runs byte-identical | CLI `cmp` gate | PLANNED |
| 16 | Clean worktree/docs match behavior | release audit | PLANNED |


## v3A release gate

**PASS.** Capability commit `24eabc9d6cd6690334eba8572115b46f7703e546` (tree `02e97672a412f12e87dbf9baeea1d364b9557d2b`) received an independent read-only final verdict of **PASS (P0=0, P1=0, P2=0)**. Fresh evidence: Ruff format/check passed, strict mypy passed over 97 source files, 130 tests passed, lock/diff/clean-tree gates passed, isolated replay/company JSON/company Markdown comparisons were byte-identical, and the final porcelain status was empty.

This accepts v3A only. Criteria 7-16 remain gated by v3B-v3D implementation and the final whole-program release audit; no later phase may weaken the accepted v3A or v2 invariants.
