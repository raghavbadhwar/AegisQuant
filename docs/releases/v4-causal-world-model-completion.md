# v4 Causal World Model — Engineering Completion Manifest

## Disposition

- Base/release commit: `579ddc13c9dae455e87b13720c5b95fa96701096`
- Engineering status: `completed`
- Evidence status: `engineering-only`
- Release status: `release-gated`
- Release eligible: `false`

This manifest records local engineering completion of the candidate-only v4
causal-world-model programme. It is retained in Git and must be independently
reviewed before it is used as the v6 engineering entry reference. It is not an
external original-record receipt, empirical validation, investment evidence,
performance evidence, calibration evidence, or production-release approval.

## Milestone commit map

| Milestone | Commit | Completed engineering capability |
| --- | --- | --- |
| v4 foundation | `0d836038f15cf5538eae514a2843f76bd5370683` | candidate causal, world snapshot, scenario, twin, experiment, uncertainty, VOI and counterfactual contracts |
| v4A | `2e7cfb37826831abeefb672a98504536745e083c` | governed causal graph storage, identification/refutation binding, discovery quarantine and inspection |
| v4B vertical slice | `f4059626d66596d86bb46fde609e2801d06b129c` | deterministic AI-infrastructure domain pack, mechanism registry and supplier-revenue twin |
| v4B hardening | `e684d5a0ea947dd06a2660c6d4f5f015fe0fa9d0` | negative intervention, protocol conformance and sealed-source lineage checks |
| v4B expansion | `fc4c270f469799a27b99d19d216babb58d0ad46c` | propagation, lags, feedback convergence, reconciliation, scenario runs, replay and FCFF adapter |
| v4C | `001e07459daa112505f5439b9df4228fa8ae016d` | deterministic bounded Monte Carlo, uncertainty, sensitivity, belief lineage and no-I/O research planning |
| v4D | `22856d4764beeb5bc60ef1b6745f37ad303b6ae5` | candidate scenario intelligence, read-only impact/exposure and abstaining post-mortems |
| v4E | `579ddc13c9dae455e87b13720c5b95fa96701096` | isolated deterministic microstructure research seam and unsupported-adapter abstention |

Every listed v4 public artefact remains candidate-only. No milestone adds live
broker connectivity, orders, weights, risk decisions, promotion authority,
network I/O to historical/replay, or factual/investment/performance claims.

## Current engineering verification

The exact base commit was validated from the isolated v6 worktree before this
manifest was authored:

```text
env -u PYTHONPATH uv run pytest -q
430 passed

env -u PYTHONPATH uv run ruff check aegis apps tests scripts/generate_demo_data.py
All checks passed!

env -u PYTHONPATH uv run ruff format --check aegis apps tests scripts/generate_demo_data.py
248 files already formatted

env -u PYTHONPATH uv run mypy aegis apps
Success: no issues found in 155 source files

env -u PYTHONPATH uv lock --check
Resolved 101 packages

git diff --check
clean
```

The governing capability and release disposition remains
`docs/V4_TRACEABILITY.md`. This manifest records completion of the specified
local engineering slices only; it does not change that document's release
state.

## Unresolved release blockers

1. No approved survivorship-safe PIT market/universe/corporate-action/delisting source.
2. Archived accession-level XBRL parsing is required for production historical revisions.
3. Dated security-master identifier history is missing.
4. N-PORT disclosure timing and raw archive-to-receipt binding need hardening.
5. Original-record verification still requires separately retained append-only governed receipts.
6. Local Yahoo and synthetic fixtures remain engineering-only.

These blockers do not prevent candidate-only v6 engineering work, but they do
prevent empirical, investment, governance, performance, and production-release
claims.
