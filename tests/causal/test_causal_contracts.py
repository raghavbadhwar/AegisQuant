from datetime import UTC, datetime, timedelta

import pytest

from aegis.causal import (
    CausalDiscoveryCandidate,
    CausalEdge,
    CausalEdgeKind,
    CausalGraphSnapshot,
    CausalSupportLevel,
    EdgeStatus,
    IdentificationRecord,
    RefutationRecord,
    RefutationStatus,
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


def passing_identification(**updates: object) -> IdentificationRecord:
    values: dict[str, object] = {
        "identification_id": "id-1",
        "method": "difference-in-differences",
        "assumption_ids": ("parallel-trends",),
        "evidence_ids": ("e-1",),
        "refutations": (
            RefutationRecord(
                refutation_id="placebo-pass",
                method="placebo-treatment",
                status=RefutationStatus.PASSED,
                assumption_ids=("parallel-trends",),
                evidence_ids=("e-1",),
                evaluated_at=NOW,
                evaluator_id="validator-1",
                reason="No placebo effect detected.",
            ),
        ),
        "validated_at": NOW,
        "validator_id": "validator-1",
    }
    values.update(updates)
    return IdentificationRecord(**values)


def test_identified_edge_requires_identification_record() -> None:
    with pytest.raises(ValueError, match="C2/C3"):
        candidate(
            kind=CausalEdgeKind.IDENTIFIED_CAUSE,
            status=EdgeStatus.SUPPORTED,
            support_level=CausalSupportLevel.C2_IDENTIFIED,
        )


def test_identified_edge_with_independent_refutation_record_is_valid() -> None:
    identification = passing_identification()
    edge = candidate(
        kind=CausalEdgeKind.IDENTIFIED_CAUSE,
        status=EdgeStatus.SUPPORTED,
        support_level=CausalSupportLevel.C2_IDENTIFIED,
        identification=identification,
        evidence_ids=("e-1",),
        assumption_ids=("parallel-trends",),
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


def test_identified_edge_requires_supported_status() -> None:
    with pytest.raises(ValueError, match="supported status"):
        candidate(
            kind=CausalEdgeKind.IDENTIFIED_CAUSE,
            support_level=CausalSupportLevel.C2_IDENTIFIED,
            identification=passing_identification(),
            evidence_ids=("e-1",),
            assumption_ids=("parallel-trends",),
        )


def test_structural_edge_requires_domain_validated_status() -> None:
    with pytest.raises(ValueError, match="validated for its domain"):
        candidate(
            kind=CausalEdgeKind.STRUCTURAL_MECHANISM,
            status=EdgeStatus.SUPPORTED,
            support_level=CausalSupportLevel.C3_STRUCTURAL,
            identification=passing_identification(),
            mechanism_model_id="mechanism-1",
            evidence_ids=("e-1",),
            assumption_ids=("parallel-trends",),
        )


def test_identification_record_must_bind_edge_evidence_assumptions_and_confounders() -> None:
    with pytest.raises(ValueError, match="bind the causal edge"):
        candidate(
            kind=CausalEdgeKind.IDENTIFIED_CAUSE,
            status=EdgeStatus.SUPPORTED,
            support_level=CausalSupportLevel.C2_IDENTIFIED,
            identification=passing_identification(),
            evidence_ids=("different-evidence",),
            assumption_ids=("parallel-trends",),
        )

    with pytest.raises(ValueError, match="adjustment set"):
        candidate(
            kind=CausalEdgeKind.IDENTIFIED_CAUSE,
            status=EdgeStatus.SUPPORTED,
            support_level=CausalSupportLevel.C2_IDENTIFIED,
            identification=passing_identification(),
            evidence_ids=("e-1",),
            assumption_ids=("parallel-trends",),
            confounder_ids=("macro-demand",),
        )


def test_identification_record_rejects_failed_refutation() -> None:
    with pytest.raises(ValueError, match="failed refutation"):
        IdentificationRecord(
            identification_id="id-failed",
            method="difference-in-differences",
            assumption_ids=("parallel-trends",),
            evidence_ids=("e-1",),
            refutations=(
                RefutationRecord(
                    refutation_id="placebo-failed",
                    method="placebo-treatment",
                    status=RefutationStatus.FAILED,
                    assumption_ids=("parallel-trends",),
                    evidence_ids=("e-1",),
                    evaluated_at=NOW,
                    evaluator_id="validator-1",
                    reason="Placebo effect remained material.",
                ),
            ),
            validated_at=NOW,
            validator_id="validator-1",
        )


def test_refutation_contract_rejects_empty_identifiers() -> None:
    with pytest.raises(ValueError, match="unique and nonempty"):
        RefutationRecord(
            refutation_id="placebo-pass",
            method="placebo-treatment",
            status=RefutationStatus.PASSED,
            assumption_ids=("",),
            evidence_ids=("e-1",),
            evaluated_at=NOW,
            evaluator_id="validator-1",
            reason="Invalid empty assumption ID.",
        )


def test_identification_record_rejects_undeclared_refutation_assumptions() -> None:
    with pytest.raises(ValueError, match="refutation assumptions"):
        passing_identification(
            refutations=(
                RefutationRecord(
                    refutation_id="placebo-pass",
                    method="placebo-treatment",
                    status=RefutationStatus.PASSED,
                    assumption_ids=("undeclared-assumption",),
                    evidence_ids=("e-1",),
                    evaluated_at=NOW,
                    evaluator_id="validator-1",
                    reason="Placebo test used an undeclared assumption.",
                ),
            )
        )


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


def test_future_identification_and_refutation_are_not_eligible() -> None:
    future = NOW + timedelta(days=1)
    identification = passing_identification(
        validated_at=future,
        refutations=(
            RefutationRecord(
                refutation_id="placebo-pass",
                method="placebo-treatment",
                status=RefutationStatus.PASSED,
                assumption_ids=("parallel-trends",),
                evidence_ids=("e-1",),
                evaluated_at=future,
                evaluator_id="validator-1",
                reason="Future-dated result.",
            ),
        ),
    )
    edge = candidate(
        kind=CausalEdgeKind.IDENTIFIED_CAUSE,
        status=EdgeStatus.SUPPORTED,
        support_level=CausalSupportLevel.C2_IDENTIFIED,
        identification=identification,
        evidence_ids=("e-1",),
        assumption_ids=("parallel-trends",),
    )
    graph = CausalGraphSnapshot(
        snapshot_id="graph-future-identification",
        as_of=NOW,
        domain_pack="ai-infrastructure-v1",
        edges=(edge,),
        evidence_ids=("e-1",),
    )

    assert graph.eligible_edges() == ()


def test_causal_discovery_output_is_quarantined_as_a_draft_hypothesis() -> None:
    discovered = CausalDiscoveryCandidate(
        discovery_id="pc-run-1",
        method="pc",
        source_variable_id="hyperscaler.ai_capex_growth",
        target_variable_id="supplier.revenue",
        mechanism_description="Candidate relationship emitted by a discovery run.",
        sign=1,
        evidence_ids=("e-1",),
        domain_pack="ai-infrastructure-v1",
        known_from=NOW,
        confidence=0.3,
    )

    quarantined = discovered.as_edge("discovered-ai-capex-to-revenue")

    assert quarantined.kind == CausalEdgeKind.HYPOTHESIZED_CAUSE
    assert quarantined.status == EdgeStatus.DRAFT
    assert quarantined.support_level == CausalSupportLevel.C0_NARRATIVE
    assert quarantined.identification is None


def test_competing_mechanisms_are_explicit_and_share_one_target() -> None:
    first = candidate(
        edge_id="capex-demand-mechanism",
        competing_mechanism_group_id="supplier-revenue-drivers",
    )
    second = candidate(
        edge_id="inventory-demand-mechanism",
        source_variable_id="customer.inventory",
        competing_mechanism_group_id="supplier-revenue-drivers",
    )

    graph = CausalGraphSnapshot(
        snapshot_id="competing-mechanisms",
        as_of=NOW,
        domain_pack="ai-infrastructure-v1",
        edges=(first, second),
        evidence_ids=("e-1",),
    )

    assert graph.edges[0].competing_mechanism_group_id == "supplier-revenue-drivers"

    with pytest.raises(ValueError, match="at least two"):
        CausalGraphSnapshot(
            snapshot_id="incomplete-competing-mechanism",
            as_of=NOW,
            domain_pack="ai-infrastructure-v1",
            edges=(first,),
            evidence_ids=("e-1",),
        )

    with pytest.raises(ValueError, match="share one target"):
        CausalGraphSnapshot(
            snapshot_id="different-competing-targets",
            as_of=NOW,
            domain_pack="ai-infrastructure-v1",
            edges=(second.model_copy(update={"target_variable_id": "supplier.margin"}), first),
            evidence_ids=("e-1",),
        )
