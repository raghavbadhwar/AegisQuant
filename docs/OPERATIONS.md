# Operations

1. Install with `uv sync --frozen --extra lab --extra dashboard`.
2. Seed an offline receipt with `uv run aegis replay data/fixtures/cases/nvda_earnings_case.json`.
3. Verify with `uv run pytest`, Ruff, mypy, and the two-replay byte comparison in CI.
4. Start the dashboard on loopback only, following `docs/DASHBOARD.md`.
5. Back up SQLite ledgers and raw content-addressed captures as immutable artifacts.

If a ledger, raw capture, evidence graph, memory item, experiment, or hash fails validation, stop and preserve it for investigation. Do not repair history in place. Source acquisition is live-research-only, allowlisted, raw-first, and invoked explicitly. Watchers emit case candidates only. All portfolio execution uses `SimBroker`.
