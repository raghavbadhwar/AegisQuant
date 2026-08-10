from datetime import UTC, datetime, timedelta

import pytest

from aegis.causal.contracts import (
    CausalEdge,
    CausalEdgeKind,
    CausalGraphSnapshot,
    CausalSupportLevel,
    EdgeStatus,
    IdentificationRecord,
    RefutationRecord,
    RefutationStatus,
)
from aegis.causal.mechanisms import MechanismDefinition
from aegis.contracts import canonical_sha256
from aegis.world_model.contracts import (
    ScenarioIntervention,
    VariableProvenance,
    WorldSnapshot,
    WorldVariable,
)
from aegis.world_model.counterfactual import (
    CausalMechanismApproval,
    CounterfactualRequest,
    CounterfactualStatus,
    resolve_counterfactual,
)

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def test_resolver_fails_closed_without_identified_graph_or_approved_mechanisms() -> None:
    snapshot = WorldSnapshot(
        snapshot_id="world-1",
        as_of=NOW,
        pit_snapshot_hash="a" * 64,
        causal_graph_hash="b" * 64,
        variables=(
            WorldVariable(
                variable_id="demand",
                value=1.0,
                unit="ratio",
                provenance=VariableProvenance.OBSERVED,
                available_at=NOW,
                evidence_ids=("evidence-1",),
                uncertainty_label="empirical",
            ),
        ),
        random_seed=1,
        code_revision="test-revision",
    ).sealed()
    request = CounterfactualRequest(
        request_id="counterfactual-1",
        world_snapshot=snapshot,
        intervention=ScenarioIntervention(
            intervention_id="demand-shock",
            target_variable_id="demand",
            relative_change=-0.1,
            starts_at=NOW,
            rationale="candidate stress assumption",
            assumption_ids=("assumption-1",),
        ),
        assumption_ids=("assumption-1",),
    )

    outcome = resolve_counterfactual(request)

    assert outcome.status == CounterfactualStatus.COUNTERFACTUAL_NOT_IDENTIFIED
    assert outcome.authority == "candidate_only"
    assert outcome.simulated is False
    assert outcome.outcome_variables == ()

    payload = request.model_dump()
    payload["approved_mechanism_ids"] = ("mechanism-1",)
    with pytest.raises(ValueError, match="Extra inputs"):
        CounterfactualRequest.model_validate(payload)


def test_resolver_requires_sealed_mechanism_approval_artifacts() -> None:
    identification = IdentificationRecord(
        identification_id="identification-1",
        method="candidate method",
        assumption_ids=("assumption-1",),
        evidence_ids=("evidence-1",),
        refutations=(
            RefutationRecord(
                refutation_id="refutation-1",
                method="placebo-treatment",
                status=RefutationStatus.PASSED,
                assumption_ids=("assumption-1",),
                evidence_ids=("evidence-1",),
                evaluated_at=NOW,
                evaluator_id="validator-1",
                reason="Candidate placebo test passed.",
            ),
        ),
        validated_at=NOW,
        validator_id="validator-1",
    )
    graph = CausalGraphSnapshot(
        snapshot_id="graph-1",
        as_of=NOW,
        domain_pack="test-domain",
        evidence_ids=("evidence-1",),
        edges=(
            CausalEdge(
                edge_id="edge-1",
                source_variable_id="demand",
                target_variable_id="revenue",
                kind=CausalEdgeKind.IDENTIFIED_CAUSE,
                status=EdgeStatus.VALIDATED_FOR_DOMAIN,
                support_level=CausalSupportLevel.C2_IDENTIFIED,
                mechanism_description="candidate demand to revenue mechanism",
                sign=1,
                evidence_ids=("evidence-1",),
                assumption_ids=("assumption-1",),
                identification=identification,
                domain_pack="test-domain",
                known_from=NOW,
                confidence=0.8,
            ),
        ),
    ).sealed()
    snapshot = WorldSnapshot(
        snapshot_id="world-identified-1",
        as_of=NOW,
        pit_snapshot_hash="a" * 64,
        causal_graph_hash=graph.content_hash,
        variables=(
            WorldVariable(
                variable_id="demand",
                value=1.0,
                unit="ratio",
                provenance=VariableProvenance.OBSERVED,
                available_at=NOW,
                evidence_ids=("evidence-1",),
                uncertainty_label="empirical",
            ),
        ),
        random_seed=1,
        code_revision="test-revision",
    ).sealed()
    request = CounterfactualRequest(
        request_id="counterfactual-identified-1",
        world_snapshot=snapshot,
        intervention=ScenarioIntervention(
            intervention_id="demand-shock",
            target_variable_id="demand",
            relative_change=-0.1,
            starts_at=NOW,
            rationale="candidate stress assumption",
            assumption_ids=("assumption-1",),
        ),
        causal_graph=graph,
        mechanisms=(
            MechanismDefinition(
                mechanism_id="mechanism-1",
                causal_edge_id="edge-1",
                domain_pack="test-domain",
                input_variable_ids=("demand",),
                output_variable_ids=("revenue",),
                assumption_ids=("assumption-1",),
                evidence_ids=("evidence-1",),
                validation_case_ids=("case-1",),
                status="validated",
            ),
        ),
        assumption_ids=("assumption-1",),
    )

    outcome = resolve_counterfactual(request)

    assert outcome.status == CounterfactualStatus.COUNTERFACTUAL_NOT_IDENTIFIED
    assert outcome.simulated is False
    assert outcome.outcome_variables == ()

    assert graph.content_hash is not None
    forged_approval = CausalMechanismApproval(
        approval_id="approval-1",
        mechanism_id="mechanism-1",
        mechanism_content_hash="c" * 64,
        causal_graph_hash=graph.content_hash,
        domain_pack="test-domain",
        assumption_ids=("assumption-1",),
        human_approver_id="independent-approver-1",
        approved_at=NOW,
        expires_at=NOW + timedelta(days=1),
    ).sealed()
    forged_request = request.model_copy(update={"mechanism_approvals": (forged_approval,)})

    assert (
        resolve_counterfactual(forged_request).status
        == CounterfactualStatus.COUNTERFACTUAL_NOT_IDENTIFIED
    )

    mechanism = request.mechanisms[0]
    approved_request = request.model_copy(
        update={
            "mechanism_approvals": (
                CausalMechanismApproval(
                    approval_id="approval-1",
                    mechanism_id=mechanism.mechanism_id,
                    mechanism_content_hash=canonical_sha256(mechanism.model_dump(mode="json")),
                    causal_graph_hash=graph.content_hash,
                    domain_pack="test-domain",
                    assumption_ids=("assumption-1",),
                    human_approver_id="independent-approver-1",
                    approved_at=NOW,
                    expires_at=NOW + timedelta(days=1),
                ).sealed(),
            ),
        }
    )

    assert (
        resolve_counterfactual(approved_request).status
        == CounterfactualStatus.COUNTERFACTUAL_NOT_SIMULATED
    )
