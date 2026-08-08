"""Read-only Streamlit observer for validated AegisQuant cycle receipts."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

from aegis.reporting import ReadOnlyRunLedger
from aegis.reporting.view_models import (
    audit_view,
    evidence_rows,
    forecast_rows,
    graph_rows,
    portfolio_rows,
    run_summary,
)

BANNER = (
    "Research, backtest, and paper simulation only — read-only dashboard — "
    "no live broker or order submission."
)
TAB_NAMES = (
    "Case Intake",
    "Agent Graph",
    "Evidence Dossier",
    "Forecast",
    "Portfolio & Risk",
    "Audit",
    "Source Monitor",
    "Memory",
    "Research Lab",
    "Learning",
)


def _streamlit() -> Any:
    try:
        return importlib.import_module("streamlit")
    except ImportError as exc:
        raise RuntimeError("install AegisQuant with the dashboard extra") from exc


def render(st: Any, ledger_path: Path) -> None:
    st.set_page_config(page_title="AegisQuant", layout="wide")
    st.title("AegisQuant Research & Paper Portfolio Console")
    st.warning(BANNER)
    try:
        records = ReadOnlyRunLedger(ledger_path).list_records()
    except Exception as exc:
        st.error(f"Ledger unavailable or failed integrity validation: {exc}")
        return
    if not records:
        st.info("The validated ledger contains no cycle receipts.")
        return
    by_id = {record.run_id: record for record in records}
    selected_id = st.selectbox("Validated run", list(by_id), index=0)
    record = by_id[selected_id]
    tabs = st.tabs(TAB_NAMES)
    with tabs[0]:
        st.subheader("Case Intake (read-only)")
        st.json(record.case.model_dump(mode="json"))
        st.json(run_summary(record))
    with tabs[1]:
        st.subheader("Agent Graph")
        st.dataframe(graph_rows(record), width="stretch")
        for artifact in record.dossier.artifacts:
            with st.expander(f"{artifact.producer_agent}: {artifact.artifact_type}"):
                st.json(artifact.model_dump(mode="json"))
    with tabs[2]:
        st.subheader("Evidence Dossier")
        st.dataframe(evidence_rows(record), width="stretch")
        if record.dossier.claim_graph:
            st.caption("Deterministic claim graph")
            st.json(record.dossier.claim_graph.model_dump(mode="json"))
        if record.dossier.evidence_audit:
            st.caption("Deterministic evidence audit")
            st.json(record.dossier.evidence_audit.model_dump(mode="json"))
    with tabs[3]:
        st.subheader("Forecast")
        st.dataframe(forecast_rows(record), width="stretch")
    with tabs[4]:
        st.subheader("Portfolio & Risk")
        st.dataframe(portfolio_rows(record), width="stretch")
        st.json(record.risk.model_dump(mode="json"))
        st.caption("Simulated orders and fills")
        st.json(
            {
                "orders": [item.model_dump(mode="json") for item in record.orders],
                "fills": [item.model_dump(mode="json") for item in record.fills],
                "positions": [item.model_dump(mode="json") for item in record.positions],
            }
        )
    with tabs[5]:
        st.subheader("Complete Audit View")
        st.success("Receipt hash and nested contract validation passed.")
        st.json(audit_view(record))
    with tabs[6]:
        st.subheader("Source Monitor")
        st.info(
            "Source health is available through typed source modules; no source DB was configured."
        )
    with tabs[7]:
        st.subheader("Memory")
        if record.dossier.memory_hits:
            st.json([hit.model_dump(mode="json") for hit in record.dossier.memory_hits])
        else:
            st.info("This run used the canonical empty memory snapshot.")
    with tabs[8]:
        st.subheader("Research Lab")
        st.info("Experiment-ledger viewing requires a separately configured read-only lab store.")
    with tabs[9]:
        st.subheader("Learning")
        st.info("Candidates remain candidate-only; this observer cannot approve or promote them.")


def main() -> None:
    ledger_path = Path(os.environ.get("AEGIS_LEDGER_PATH", "run_data/aegisquant.sqlite"))
    render(_streamlit(), ledger_path)


if __name__ == "__main__":
    main()
