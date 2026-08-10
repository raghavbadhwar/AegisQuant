# v6 Verification Plan

## Test layers

| Layer | Required proof |
| --- | --- |
| Contract unit | frozen/forbid, exact SHA-256 sealing, model-copy revalidation, nested reconstruction, finite/bounded numeric values |
| Research graph | two competing falsifiable hypotheses, sealed PIT/receipt binding, bounded team/tree parentage/depth/critique, preregistration before run, no post-run plan alteration |
| Ledger | record-before-result, idempotence, commitment-chain verification, tampered/replaced record denial, failed/inconclusive trial retention |
| PIT and execution | sealed source/snapshot/retained-receipt binding, no future inputs, no network source path, only registered deterministic fixture evaluator, unsupported evaluator abstention |
| Identity and capability | distinct proposer/verifier/approver/replicator, exact role-to-tool allowlist, denied broker/risk/execution/promotion/source grants, candidate boundary intact |
| Verification | no verified claim without independent replication, limited claim label retained, report cannot exceed package scope, abstention has no conclusion |
| Portfolio | finite validity/value/novelty/fit and compute/data/review/redundancy costs, exact priority/reconciliation, non-positive/redundant/budget/deadline stop reason, byte-identical same inputs |
| Presentation | CLI/dashboard is read-only, rejects mutation/execution flags, malformed store fails safely |
| Regression | all pre-v6 tests, Ruff, format, mypy, lock, diff and deterministic replay remain green |

## Focused RED-to-GREEN commands

```bash
env -u PYTHONPATH uv run pytest -q tests/research_lab/test_science.py::test_research_programme_requires_two_competing_hypotheses
env -u PYTHONPATH uv run pytest -q tests/research_lab/test_science.py::test_research_tree_rejects_duplicate_active_hypothesis_and_excess_depth
env -u PYTHONPATH uv run pytest -q tests/research_lab/test_science.py::test_research_portfolio_reconciles_compute_data_review_and_redundancy_costs
env -u PYTHONPATH uv run pytest -q tests/research_lab/test_science.py
env -u PYTHONPATH uv run ruff check aegis apps tests
env -u PYTHONPATH uv run mypy aegis apps
```

## Full gate before every v6 milestone commit

```bash
env -u PYTHONPATH uv run pytest -q
env -u PYTHONPATH uv run ruff check aegis apps tests scripts/generate_demo_data.py
env -u PYTHONPATH uv run ruff format --check aegis apps tests scripts/generate_demo_data.py
env -u PYTHONPATH uv run mypy aegis apps
env -u PYTHONPATH uv lock --check
git diff --check
git status --short --branch
```

Two independently created deterministic programme fixtures must produce
byte-identical sealed archive/report output. The final audit must attempt
forged nested contracts, altered hashes, altered sealed plans, replaced ledger
rows, missing trials, future input, self-replication, self-approval, budget
overrun, report-strength inflation, omitted automatically surfaced negative
results, team/depth/critique bypass, unsupported executor, prohibited imports,
and command/view mutation attempts.

## Completion evidence

The v6 report records exact commands, cwd, base/HEAD commits, tool versions,
exit statuses, focused/full test output, deterministic fixture hashes, audit
findings and fixes, dependency/licence review, and the current release
disposition. A green local gate establishes engineering evidence only; it does
not satisfy the pre-existing empirical/release blockers.
