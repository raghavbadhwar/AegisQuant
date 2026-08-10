# v6 Implementation Plan — Autonomous Investment Scientist

## Base and release boundary

- Base branch/commit: `upgrade/aegisquant-v3-institutional-os` at
  `579ddc13c9dae455e87b13720c5b95fa96701096`.
- Working branch: `upgrade/aegisquant-v6-investment-scientist`.
- Release disposition: engineering-only and release-gated until every v6 gate
  and the existing PIT/receipt blockers are independently satisfied.
- Rollback: revert only the scoped v6 commits or abandon this isolated worktree;
  never modify the v4 branch in place.

## File plan

| File | Change |
| --- | --- |
| `aegis/research_lab/science.py` | new sealed v6 research/evidence/team/tree/portfolio contracts, role grant policy, pure archive/search/ranking functions, and the adapter to `ExperimentLedger` |
| `aegis/research_lab/__init__.py` | export the v6 public research surface only |
| `tests/research_lab/test_science.py` | contract, PIT/receipt, identity, team/tree, preregistration, ledger-first, abstention, negative-result surfacing, portfolio reconciliation, and byte-identical replay tests |
| `apps/cli.py` | add only a candidate-only `science view` command that accepts already-sealed local JSON; no executor command or source I/O |
| `apps/dashboard.py` | add a read-only supplied-science-ledger view using existing Streamlit patterns |
| `tests/acceptance/test_cli_demo.py` | prove the science command is read-only and rejects mutation/execution options |
| `tests/acceptance/test_dashboard.py` | prove the observer has no action controls and failure-safe rendering |
| `docs/architecture/v6-architecture.md` | this architecture authority |
| `docs/plans/v6-implementation-plan.md` | this TDD and commit plan |
| `docs/security/v6-threat-model.md` | v6 threats and mitigations |
| `docs/testing/v6-verification-plan.md` | v6 verification matrix |
| `docs/releases/v6-acceptance-gates.md` | v6 entry/release gates and evidence register |
| `docs/releases/v6-dependency-license-review.md` | required locked dependency inventory, licence/source review, and approval record before v6 release |
| `docs/releases/v4-causal-world-model-completion.md` | Git-retained, independently reviewed engineering-completion reference for the v6 entry gate; never empirical release evidence |

There are no migrations and no dependencies to add. v6 reuses SQLite through
`ExperimentLedger`; it does not add tables or write a second ledger. The project
is MIT, but that does not establish dependency licences. Before v6 release,
`docs/releases/v6-dependency-license-review.md` must record the exact `uv.lock`
package/version/source inventory (including enabled extras), each licence or
unknown status, approval decision, and any attribution obligation. Optional
MLflow, Ray, Dask, PyMC, SALib, container workers, and external agent managers
are not used.

## TDD slices

1. **Research graph and provenance contracts.** Write RED tests named
   `test_research_programme_requires_two_competing_hypotheses` and
   `test_research_evidence_binding_rejects_future_or_unretained_provenance`,
   then implement the smallest frozen, sealed programme/family/hypothesis,
   provenance, novelty, and plan records. Prove invalid `model_copy`, duplicate
   IDs, future lifecycle ordering, unsealed children, missing receipt binding,
   and mutable locked fields fail closed.
2. **Bounded teams and progressive tree.** Start RED with
   `test_research_tree_rejects_duplicate_active_hypothesis_and_excess_depth`.
   Add `ResearchTeam`/`ResearchTree` with deterministic team/depth/cost limits,
   parentage, critique-before-run, replication-only duplicate exception, and
   explicit role-grant denials. Do not add an agent loop or worker framework.
3. **Ledger-first trial record.** Write a RED test that a completed run cannot
   be returned unless an exact v6 payload is persisted through
   `ExperimentLedger`. Adapt its existing `ExperimentRecord` envelope; prove
   reload/tampering/mismatched code-tree-data-seed and missing preregistration
   fail. Do not create another SQLite store.
4. **Verification and negative results.** Start RED with a self-replicated
   verified claim and a novelty report omitting an automatically surfaced prior
   negative result. Add replication identity separation, the deterministic
   mechanism/assumption matching rule, verifier/approver separation,
   limited/abstained claim ceilings, and contribution no-double-counting.
5. **Research portfolio.** Start RED with
   `test_research_portfolio_reconciles_compute_data_review_and_redundancy_costs`.
   Implement the explicit bounded priority-score contract with data/review/
   redundancy/deadline inputs and stop reasons. Existing VOI is an optional
   no-positive cross-check only. The portfolio never initiates work or capital
   allocation.
6. **Read-only presentation.** Start RED with a report stronger than its
   verification package. Add JSON/read-only view, then the narrow `science view`
   CLI/dashboard observers. Reject command flags that could create, run,
   approve, promote, or acquire data.

For each slice: focused RED test; smallest implementation; focused GREEN test;
affected-module tests; then the full repository gate. Do not batch production
code ahead of RED tests.

## Commit sequence

1. `docs: define v6 research institution release gates`
2. `feat: add sealed v6 research graph and provenance contracts`
3. `feat: add bounded v6 research teams and progressive tree`
4. `feat: bind v6 research trials to append-only ledger`
5. `feat: add v6 verification and negative-result archive`
6. `feat: add bounded v6 research portfolio and read-only views`
7. `docs: record v6 engineering evidence and release disposition`

Each substantive commit is independently read-only audited after a complete
gate. Fix material findings test-first, rerun the gate, then re-audit before
commit/push. Never blanket-stage unrelated files.

## Permission and failure decisions

No permissions change. v6 roles retain no broker, execution, risk, promotion,
or unrestricted source grants. Historical/replay remain network-denied.
Malformed/unsealed data, missing ledger support, unsupported executor, missing
replication, role collision, future-dated input, budget breach, and unverified
claim strength are all typed denial/abstention paths. Data-integrity failure
halts the operation rather than returning a conclusion.

## Independent audit scope

Audit every new public contract for model-copy bypasses, nested revalidation,
hash/lineage substitution, direct SQLite bypasses, preregistration ordering,
hidden-trial paths, role/capability escalation, team/depth/critique bypass,
future or forged receipt provenance, report-strength inflation, missing
automatic negative-result surfacing, budget/denominator overflow, network
imports, and any import of fund/broker/risk/promotion authority.
