# v7 adaptive research observer

v7 is candidate-only, engineering-only, and release-gated. It has no approval,
promotion, deployment, portfolio, broker, order, or network-replay authority.

Validate a sealed local report only with its required local evidence index:

```bash
uv run aegis science adaptive-view REPORT.json --evidence-index adaptive-evidence.sqlite
```

The command is read-only. A missing, tampered, stale, or substituted index rejects the
report; a registered evaluator mismatch also rejects it. The local SQLite index proves
local consistency only, not external receipt custody, authenticated provenance, or
empirical validity.

For the read-only observer, install the existing dashboard extra and bind loopback only:

```bash
uv sync --extra dashboard
AEGIS_ADAPTIVE_REPORT_PATH=REPORT.json \
AEGIS_ADAPTIVE_EVIDENCE_INDEX_PATH=adaptive-evidence.sqlite \
uv run streamlit run apps/dashboard.py --server.address 127.0.0.1
```

Rollback is simply selecting an earlier sealed report; histories are immutable and no
v7 artifact changes an active model or research state.
