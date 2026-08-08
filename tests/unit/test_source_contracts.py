from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegis.contracts import Claim, ClaimEdge, SourceAttempt, SourceRequest
from aegis.evidence import build_claim_graph
from aegis.sources import SourcePlanner, SourceRegistry
from aegis.sources.health import source_health
from aegis.sources.planner import SourcePlanningError
from aegis.sources.watchers import changed_event

ROOT = Path(__file__).resolve().parents[2]


def test_source_planner_is_official_first_and_mode_gated() -> None:
    registry = SourceRegistry.load(ROOT / "configs/sources")
    planner = SourcePlanner(registry)
    request = SourceRequest(
        case_id="case",
        information_type="company_announcement",
        query="update",
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        mode="live_research",
        max_sources=1,
        max_cost_usd=0.0,
    )
    plan = planner.plan(request)
    assert plan.source_ids == ["company-ir"]
    with pytest.raises(SourcePlanningError, match="forbidden in replay"):
        planner.plan(request.model_copy(update={"mode": "replay"}))


def test_claim_graph_rejects_illegal_edges_and_material_claims_without_evidence() -> None:
    with pytest.raises(ValueError, match="material claims require"):
        Claim(
            claim_id="missing",
            case_id="case",
            statement="Unsupported material statement",
            claim_type="factual",
            material=True,
        )
    with pytest.raises(ValueError, match="illegal claim-graph edge"):
        ClaimEdge(
            edge_id="bad",
            source_kind="forecast",
            source_id="forecast",
            relation="SUPPORTS",
            target_kind="claim",
            target_id="claim",
        )


def test_claim_graph_hash_is_canonical() -> None:
    claim = Claim(
        claim_id="claim",
        case_id="case",
        statement="Supported",
        claim_type="factual",
        material=True,
        evidence_ids=["evidence"],
    )
    edge = ClaimEdge(
        edge_id="edge",
        source_kind="evidence",
        source_id="evidence",
        relation="SUPPORTS",
        target_kind="claim",
        target_id="claim",
    )
    assert build_claim_graph("case", [claim], [], [edge]) == build_claim_graph(
        "case", [claim], [], [edge]
    )


def test_source_health_and_watchers_are_point_in_time_and_event_only() -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    attempts = [
        SourceAttempt(
            source_id="source",
            attempted_at=now,
            success=True,
            latency_ms=10,
            citation_useful=True,
        ),
        SourceAttempt(
            source_id="source",
            attempted_at=now.replace(day=9),
            success=False,
            latency_ms=100,
        ),
    ]
    health = source_health("source", now, attempts)
    assert health.attempts == 1 and health.status == "healthy"
    assert changed_event(
        source_id="source",
        entity_ids=["AAPL"],
        previous_hash="a" * 64,
        current_hash="b" * 64,
        detected_at=now,
        evidence_ids=["evidence"],
    ).requires_case
    assert (
        changed_event(
            source_id="source",
            entity_ids=["AAPL"],
            previous_hash="a" * 64,
            current_hash="a" * 64,
            detected_at=now,
            evidence_ids=["evidence"],
        )
        is None
    )
