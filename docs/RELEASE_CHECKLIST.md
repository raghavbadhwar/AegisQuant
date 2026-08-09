# Release Checklist

A release is blocked unless every applicable command exits zero:

```bash
uv sync --frozen --extra lab --extra dashboard
uv run ruff format --check aegis apps tests scripts
uv run ruff check aegis apps tests scripts
uv run mypy aegis apps
uv run pytest -q
uv lock --check
git diff --check
test -z "$(git status --porcelain=v1 --untracked-files=all)"
```

Also run two isolated replay ledgers and `cmp` their stdout; verify ledger reconciliation/tamper tests, source and memory PIT denial, qtype/purged-CV preflight, locked candidate boundaries, independent evaluation/human promotion, dashboard no-mutation, dependency licenses, and a final tree digest. Record command, cwd, versions, exit code, and logs. No conditional release and no live-broker exception.


## v3 incremental gates

- **v3A:** standalone company-research CLI; exact PIT filing/statement amounts; reversible adjustments; closed calculation lineage; three cases; DCF cross-check and monotonicity; reverse-DCF round trip/no-root; specialist evidence confinement; unsupported-archetype abstention; seven frozen golden profiles.
- **v3B:** PIT universe/factor/event/regime contracts; purging/embargo and visible simple baselines; pod isolation; deterministic blending, allocation, contribution-preserving netting and the single existing `run_cycle` seam.
- **v3C:** restart-safe persistent paper state and idempotent schedule/event triggers through that same financial cycle; dashboard remains an observer.
- **v3D:** outcome attribution, PIT institutional memory, champion/challenger shadow isolation, independent hash-bound promotion and rollback.

A later phase cannot start until the prior phase's full repository gates pass. A phase PASS does not waive final criteria 14-16 in `docs/V3_TRACEABILITY.md`.
