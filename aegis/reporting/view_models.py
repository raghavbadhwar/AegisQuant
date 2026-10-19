"""Pure typed cycle-to-dashboard transformations."""

from __future__ import annotations

from typing import Any

from aegis.fund.ledger import CycleRecord


def run_summary(record: CycleRecord) -> dict[str, Any]:
    return {
        "run_id": record.run_id,
        "case_id": record.case.case_id,
        "mode": "simulated paper" if record.case.mode == "live_research" else record.case.mode,
        "as_of": record.case.as_of,
        "nav_after": record.nav_after,
        "cash_after": record.cash_after,
        "orders": len(record.orders),
        "fills": len(record.fills),
        "risk_approved": record.risk.decision.approved,
        "integrity_digest": record.digest(),
    }


def graph_rows(record: CycleRecord) -> list[dict[str, Any]]:
    return [event.model_dump(mode="json") for event in record.dossier.graph_events]


def evidence_rows(record: CycleRecord) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in record.evidence.records]


def forecast_rows(record: CycleRecord) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in record.forecasts]


def portfolio_rows(record: CycleRecord) -> list[dict[str, Any]]:
    tickers = sorted(set(record.portfolio.target_weights) | set(record.risk.decision.final_weights))
    return [
        {
            "ticker": ticker,
            "proposed_weight": record.portfolio.target_weights.get(ticker, 0.0),
            "final_weight": record.risk.decision.final_weights.get(ticker, 0.0),
        }
        for ticker in tickers
    ]


def audit_view(record: CycleRecord) -> dict[str, Any]:
    return {
        "record_digest": record.digest(),
        "dossier_hash": record.dossier.content_hash,
        "claim_graph_hash": (
            record.dossier.claim_graph.content_hash if record.dossier.claim_graph else None
        ),
        "memory_snapshot_hash": record.dossier.memory_snapshot_hash,
        "code_tree_hash": record.reproducibility.code_tree_hash,
        "environment_lock_hash": record.reproducibility.environment_lock_hash,
        "data_snapshot_hash": record.reproducibility.data_snapshot_hash,
        "dataset_hash": record.reproducibility.dataset_hash,
        "model_deployments": record.reproducibility.model_deployments,
        "prompt_versions": record.reproducibility.prompt_versions,
        "skill_versions": record.reproducibility.skill_versions,
    }
