from datetime import UTC, datetime

import pytest

from aegis.causal import (
    CausalEdge,
    CausalEdgeKind,
    CausalGraphSnapshot,
    CausalSupportLevel,
    EdgeStatus,
    IdentificationRecord,
    RefutationRecord,
    RefutationStatus,
    causal_graph_view,
)

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def edge(**updates: object) -> CausalEdge:
    values: dict[str, object] = {
        "edge_id": "candidate-edge",
        "source_variable_id": "hyperscaler.ai_capex_growth",
        "target_variable_id": "supplier.revenue",
        "kind": CausalEdgeKind.HYPOTHESIZED_CAUSE,
        "status": EdgeStatus.DRAFT,
        "support_level": CausalSupportLevel.C0_NARRATIVE,
        "mechanism_description": "Candidate demand transmission mechanism.",
        "sign": 1,
        "evidence_ids": ("filing-1",),
        "assumption_ids": ("capacity-available",),
        "domain_pack": "ai-infrastructure-v1",
        "known_from": NOW,
        "confidence": 0.2,
    }
    values.update(updates)
    return CausalEdge(**values)


def identified_edge() -> CausalEdge:
    return edge(
        edge_id="identified-edge",
        kind=CausalEdgeKind.IDENTIFIED_CAUSE,
        status=EdgeStatus.SUPPORTED,
        support_level=CausalSupportLevel.C2_IDENTIFIED,
        identification=IdentificationRecord(
            identification_id="id-1",
            method="difference-in-differences",
            assumption_ids=("capacity-available",),
            evidence_ids=("filing-1",),
            refutations=(
                RefutationRecord(
                    refutation_id="placebo-pass",
                    method="placebo-treatment",
                    status=RefutationStatus.PASSED,
                    assumption_ids=("capacity-available",),
                    evidence_ids=("filing-1",),
                    evaluated_at=NOW,
                    evaluator_id="independent-validator",
                    reason="Golden placebo test passed.",
                ),
            ),
            validated_at=NOW,
            validator_id="independent-validator",
        ),
    )


def test_view_never_labels_c0_c1_or_ineligible_edges_as_identified() -> None:
    graph = CausalGraphSnapshot(
        snapshot_id="causal-view-1",
        as_of=NOW,
        domain_pack="ai-infrastructure-v1",
        edges=(
            edge(),
            edge(
                edge_id="predictive-edge",
                kind=CausalEdgeKind.PREDICTS,
                status=EdgeStatus.SUPPORTED,
                support_level=CausalSupportLevel.C1_TEMPORAL_PREDICTIVE,
            ),
            identified_edge(),
            edge(
                edge_id="unsupported-edge",
                kind=CausalEdgeKind.HYPOTHESIZED_CAUSE,
                status=EdgeStatus.REFUTED,
            ),
        ),
        evidence_ids=("filing-1",),
    ).sealed()

    rows = {row["edge_id"]: row for row in causal_graph_view(graph)["edges"]}

    assert rows["candidate-edge"]["identification"] == "not_identified"
    assert rows["predictive-edge"]["identification"] == "not_identified"
    assert rows["unsupported-edge"]["identification"] == "not_identified"
    assert rows["identified-edge"]["identification"] == "identified_candidate"
    assert causal_graph_view(graph)["authority"] == "candidate_only"


def test_view_requires_a_sealed_graph() -> None:
    graph = CausalGraphSnapshot(
        snapshot_id="causal-view-unsealed",
        as_of=NOW,
        domain_pack="ai-infrastructure-v1",
        edges=(edge(),),
        evidence_ids=("filing-1",),
    )

    with pytest.raises(ValueError, match="sealed"):
        causal_graph_view(graph)
