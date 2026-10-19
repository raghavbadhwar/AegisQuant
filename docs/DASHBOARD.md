# Dashboard

The Streamlit application is a read-only observer over validated `CycleRecord` rows. It never imports `run_cycle`, invokes a provider, writes the ledger, approves candidates, or submits orders. Tabs expose the case, graph events/artifacts, evidence and claim graph, forecasts, proposed/final weights, risk clamps, simulated fills, memory context, and reproducibility hashes.

```bash
uv sync --extra dashboard
AEGIS_LEDGER_PATH=run_data/aegisquant.sqlite uv run streamlit run apps/dashboard.py --server.address 127.0.0.1
```

The ledger path is server-controlled. Missing, malformed, or tampered rows fail closed. “Paper” always means simulated paper; there is no live broker.
