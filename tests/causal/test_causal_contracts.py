from datetime import UTC, datetime

import pytest

from aegis.causal import (
    CausalEdge,
    CausalEdgeKind,
    CausalGraphSnapshot,
    CausalSupportLevel,
    EdgeStatus,
    IdentificationRecord,
)

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def candidate(**updates: object) -> CausalEdge:
    values: dict[str, object] = {
        "edge_id": "edge-1",
        "source_variable_id": "capex",
        "target_variable_id": "revenue",
        "kind": CausalEdgeKind.HYPOTHESIZED_CAUSE,
        "status": EdgeStatus.DRAFT,
        "support_level": CausalSupportLevel.C0_NARRATIVE,
        "mechanism_description": "candidate",
        "sign": 1,
        "domain_pack": "ai-infrastructure-v1",
        "known_from": NOW,
        "confidence": 0.2,
    }
    values.update(updates)
    return CausalEdge(**values)


def test_identified_edge_requires_identification_record() -> None:
    with pytest.raises(ValueError, match="C2/C3"):
        candidate(
            kind=CausalEdgeKind.IDENTIFIED_CAUSE, support_level=CausalSupportLevel.C2_IDENTIFIED
        )


def test_identified_edge_with_independent_refutation_record_is_valid() -> None:
    identification = IdentificationRecord(
        identification_id="id-1",
        method="difference-in-differences",
        assumption_ids=("parallel-trends",),
        evidence_ids=("e-1",),
        refutation_ids=("placebo-pass",),
        validated_at=NOW,
        validator_id="validator-1",
    )
    edge = candidate(
        kind=CausalEdgeKind.IDENTIFIED_CAUSE,
        status=EdgeStatus.SUPPORTED,
        support_level=CausalSupportLevel.C2_IDENTIFIED,
        identification=identification,
        evidence_ids=("e-1",),
    )
    snapshot = CausalGraphSnapshot(
        snapshot_id="graph-1",
        as_of=NOW,
        domain_pack="ai-infrastructure-v1",
        edges=(edge,),
        evidence_ids=("e-1",),
    ).sealed()
    assert snapshot.content_hash
    assert snapshot.eligible_edges() == (edge,)


def test_future_or_refuted_edge_is_not_eligible() -> None:
    future = candidate(known_from=datetime(2025, 1, 1, tzinfo=UTC))
    refuted = candidate(edge_id="edge-2", status=EdgeStatus.REFUTED)
    graph = CausalGraphSnapshot(
        snapshot_id="graph-1",
        as_of=NOW,
        domain_pack="ai-infrastructure-v1",
        edges=(future, refuted),
        evidence_ids=(),
    )
    assert graph.eligible_edges() == ()
