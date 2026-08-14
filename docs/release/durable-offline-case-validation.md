# Durable offline case candidate — exact validation

- **Validated code:** `2f05a8c593ecf1d0d1ba254d12a2690d4beebdf7`
- **Date:** 2026-08-14
- **Profile:** local fixture-only research and `SIM`/`PAPER`; no live execution or production claim

## Reproducibility and recovery evidence

Two independent CLI runs of `multi_asset_control.json` were byte-identical:

```text
SHA-256  2b6b2e71eae1f06d6f1bc09e90195ad0db4ea9a9a0bacd6d817cbc3c43de4b76
```

The ephemeral PostgreSQL retry scenario called the execution and reconciliation functions twice
with identical inputs and asserted these authoritative counts:

```text
consumed risk decisions      1
paper execution results     1
persisted fills              1
account snapshots            2
prepared events              1
execution-recorded events    1
reconciled events            1
cross-tenant visible results 0
```

Temporal time-skipping tests inject retryable failures before authorization, before execution
commit, after execution commit, and after reconciliation commit. Every path returns one coherent
execution/result digest and one reconciliation. The committed V1 durable workflow history also
replays offline without nondeterminism.

## Complete gate

```bash
uv lock --check
scripts/verify.sh
git diff --check
```

Observed at the validated code commit:

```text
Ruff format/lint     passed
mypy                 50 source files passed
JSON Schemas         current
pytest               168 passed
PostgreSQL gate      passed
```

## Independent review and limits

Independent read-only review returned `READY` after typed source verification, exact case/holdout
bindings, V1 compatibility, signed evaluator/human separation, approval expiry, and current-key
revocation/backdating denials were verified. A whole-candidate pass also removed callable network
ingress, sealed holdout entry state, enforced compounded OOS/benchmark/cash-placebo/single-trial
controls, and made delisting terminal for each security version.

This evidence does not establish investment performance, calibration, custody safety, production
operations, customer use, legal approval, broker connectivity, or live-trading readiness.
