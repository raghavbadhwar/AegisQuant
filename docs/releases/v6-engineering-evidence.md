# v6 Engineering Evidence Manifest

## Scope and disposition

- Worktree: `/Volumes/RAGHAV2/Development_Projects/aegisquant-v6`
- Branch: `upgrade/aegisquant-v6-investment-scientist`
- Base: `579ddc13c9dae455e87b13720c5b95fa96701096`
- Implemented-through commit: `830edd54aff2b82aae02de2f2c8c561ce93d44e4`
- Disposition: `completed`, `engineering-only`, and `release-gated`.

This manifest records local deterministic engineering evidence. It is not an
external original-record receipt and makes no empirical, calibration,
performance, investment, governance, eligibility, or production-readiness
claim.

## Commit map

| Commit | Capability |
| --- | --- |
| `1893ef2e154d02714b25462e05e4e7634426e3f1` | v6 architecture, implementation, verification, threat, and acceptance gates |
| `733bca40b73aa36ed3ae04e53590bcdfe203ee2a` | independently reviewed v4 engineering-completion entry reference |
| `21ff0866e27be1ae382d10126b18516130c28b9a` | sealed research programme, hypothesis, provenance, novelty, and plan contracts |
| `aa78abd4154db978bc5e7cffab29066e40f56e37` | bounded teams, progressive tree, critique, replication branches, and role grants |
| `ce3670520609b52f5a79e560b047bc89c9e91c40` | preregistered deterministic fixture runs bound to the append-only experiment ledger |
| `7109052a018b662fba04839713d86bdea414d939` | independent verification, negative archive, contributions, and postmortems |
| `9b1a419e3663dbc2b9222accb6ab4c9892b1ec5f` | bounded deterministic research-portfolio ranking and stop reasons |
| `830edd54aff2b82aae02de2f2c8c561ce93d44e4` | sealed science report plus read-only CLI and dashboard observers |

## Requirement-by-requirement engineering evidence

| Gate | Evidence | Engineering status |
| --- | --- | --- |
| 1. Competing hypotheses | `test_research_programme_requires_two_competing_hypotheses` and sealed `ResearchProgramme`/`HypothesisFamily` validation | completed |
| 2. Preregistration and ledger-first return | `test_completed_run_is_persisted_before_return`; exact `ExperimentRecord` reload before return | completed |
| 3. Candidate cannot control locked boundaries | exact governed fixture policy values, closed fixture executor set, role-grant denial tests, candidate-only contracts | completed |
| 4. Negative and inconclusive archive | `ResearchArchive`, deterministic prior surfacing, novelty-report completeness denial | completed |
| 5. Independent replication and claim ceiling | exact ledger-context verification for claims and verified reports, replication identity separation, limited/abstained ceiling tests | completed |
| 6. Identity separation | proposer, author, replicator, reviewer, verifier, and approver collision denials | completed |
| 7. Bounded ranking | exact finite cost/VOI/score recomputation, stable ordering, component/total budgets, six stop reasons | completed |
| 8. Teams and tree | parent/depth/team/compute limits, critique-before-preregistration, stopped lifecycle, replication-only duplication | completed |
| 9. Determinism | registered-fixture result/status recomputation before persistence, byte-identical seeded history, portfolio ordering, and canonical report tests | completed |
| 10. No v6 authority or historical network path | closed v6 tool grants; view-only CLI; no-action dashboard; static audit scans | completed |
| 11. Full gate and independent audit | full gate below is green; final independent exact-state re-audit found no material findings | completed |
| 12. Dependency/licence record | `docs/releases/v6-dependency-license-review.md` reconciles all 101 locked packages; v6 adds none | recorded; release approval pending |

## Validation evidence

Commands ran from the isolated worktree with injected `PYTHONPATH` removed:

```text
env -u PYTHONPATH uv run pytest -q
453 passed in 38.07s

env -u PYTHONPATH uv run ruff check aegis apps tests scripts/generate_demo_data.py
All checks passed!

env -u PYTHONPATH uv run ruff format --check aegis apps tests scripts/generate_demo_data.py
250 files already formatted

env -u PYTHONPATH uv run mypy aegis apps
Success: no issues found in 156 source files

env -u PYTHONPATH uv lock --check
Resolved 101 packages in 2ms

git diff --check
clean
```

Toolchain: `uv 0.11.15`, `Python 3.12.13`, `pytest 9.1.1`,
`ruff 0.16.2`, and `mypy 1.20.2`.

Independent audit evidence retained during implementation includes:

- teams/tree re-audit: no material findings; focused `11 passed`;
- ledger re-audit: no material findings; focused `23 passed`;
- verification/archive re-audit: no material findings; full repository `446 passed`;
- portfolio re-audit: no material findings; focused `4 passed` and module `18 passed`;
- report/CLI/dashboard re-audit: no material findings after lineage fix; explicit `4 passed`.
- final requirement audit after shared evaluator fixes: no material findings;
  focused `6 passed`, full repository `453 passed`.

Every material audit finding was fixed test-first and re-audited before its
milestone commit.

## Release blockers

The following are unchanged and cannot be cleared by local code or fixtures:

- no approved survivorship-safe PIT market, universe, corporate-action, and
  delisting source;
- archived accession-level XBRL revisions and dated identifier history remain
  incomplete;
- N-PORT timing and raw-archive-to-receipt binding still require hardening;
- externally retained append-only original-record receipts are unavailable;
- dependency distribution approval and upstream attribution review remain
  pending, including two `UNKNOWN` local licence metadata rows;
- local Yahoo and synthetic/registered fixtures are engineering-only and cannot
  establish empirical or release claims.

Accordingly, v6 has no broker, order, execution, portfolio/risk decision,
promotion, spending, or external-side-effect authority.
