# AegisQuant v3 Traceability

Authoritative inputs: `docs/specs/AegisQuant_v3_Institutional_Investment_OS_Spec.md` and `docs/specs/AegisQuant_v3_Institutional_Codex_Master_Prompt.md`.

Status is `PLANNED`, `IN PROGRESS`, or `PASS`; only named deterministic tests may move a criterion to PASS.

| # | Final acceptance criterion | Verification | Status |
|---|---|---|---|
| 1 | Company research independent of fund | v3A service/CLI tests | PLANNED |
| 2 | Deterministic calculations and evidence lineage | v3A lineage/audit tests | PLANNED |
| 3 | DCF/reverse DCF assumptions, ranges, sensitivities | valuation golden/property tests | PLANNED |
| 4 | Agents use verified calculations | graph authority/adversarial tests | PLANNED |
| 5 | Personas optional, not voters | prompt/capability tests | PLANNED |
| 6 | Backtestable calibrated fundamental forecast | dossier/forecast integration | PLANNED |
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
