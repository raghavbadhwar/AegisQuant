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
```

Also run two isolated replay ledgers and `cmp` their stdout; verify ledger reconciliation/tamper tests, source and memory PIT denial, qtype/purged-CV preflight, locked candidate boundaries, independent evaluation/human promotion, dashboard no-mutation, dependency licenses, and a final tree digest. Record command, cwd, versions, exit code, and logs. No conditional release and no live-broker exception.
