from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aegis.contracts import canonical_sha256
from aegis.harness.capability_broker import CapabilityDenied
from aegis.reporting.traceability import SnapshotReference, SourceProvenanceReference
from aegis.research_lab.science import (
    ExperimentPlan,
    Hypothesis,
    HypothesisFamily,
    NoveltyReport,
    ResearchArtifactReceiptReference,
    ResearchBudget,
    ResearchCritiqueReceipt,
    ResearchEvidenceBinding,
    ResearchProgramme,
    ResearchTeam,
    ResearchTree,
    ResearchTreeNode,
    authorize_v6_research_tool,
)

AS_OF = datetime(2026, 1, 15, tzinfo=UTC)
LOCKED_FIELDS = (
    "dataset_snapshot_hash",
    "split_policy_id",
    "metric_ids",
    "baseline_ids",
    "ablation_ids",
    "cost_model_id",
    "stop_rules",
)


def _evidence_binding(
    *,
    as_of: datetime = AS_OF,
    source_available_at: datetime | None = None,
    retained_hash: str | None = None,
) -> ResearchEvidenceBinding:
    source_available_at = source_available_at or as_of - timedelta(days=1)
    sources = (
        SourceProvenanceReference(
            source_id="source-1",
            artifact_id="source-artifact-1",
            content_hash="a" * 64,
            available_at=source_available_at,
        ),
    )
    snapshot = SnapshotReference(
        snapshot_id="snapshot-1",
        content_hash="b" * 64,
        as_of=as_of,
    )
    artifact_hash = canonical_sha256(
        {
            "as_of": as_of,
            "source_provenance": sources,
            "snapshot": snapshot,
        }
    )
    receipt = ResearchArtifactReceiptReference(
        receipt_id="receipt-1",
        artifact_id="evidence-binding-1",
        artifact_content_hash=retained_hash or artifact_hash,
        recorded_at=as_of + timedelta(minutes=1),
    ).sealed()
    return ResearchEvidenceBinding(
        binding_id="evidence-binding-1",
        as_of=as_of,
        source_provenance=sources,
        snapshot=snapshot,
        original_receipt=receipt,
    ).sealed()


def _hypothesis(
    hypothesis_id: str,
    mechanism_id: str,
    competitor_id: str,
    evidence_binding: ResearchEvidenceBinding,
) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=hypothesis_id,
        programme_id="programme-1",
        mechanism_id=mechanism_id,
        statement=f"Candidate statement for {mechanism_id}.",
        falsifiable_predictions=(f"prediction-{hypothesis_id}",),
        assumption_ids=(f"assumption-{hypothesis_id}",),
        known_failure_condition=f"failure-{hypothesis_id}",
        competes_with=(competitor_id,),
        proposer_id="hypothesis-architect-1",
        evidence_binding=evidence_binding,
    ).sealed()


def _programme(*, max_tree_depth: int = 2) -> ResearchProgramme:
    binding = _evidence_binding()
    first = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", binding)
    second = _hypothesis("hypothesis-b", "mechanism-b", "hypothesis-a", binding)
    family = HypothesisFamily(
        family_id="family-1",
        programme_id="programme-1",
        hypotheses=(first, second),
    ).sealed()
    budget = ResearchBudget(
        compute_limit=10.0,
        data_limit=5.0,
        review_limit=3.0,
        total_limit=18.0,
    ).sealed()
    return ResearchProgramme(
        programme_id="programme-1",
        mandate="Test competing candidate mechanisms.",
        as_of=AS_OF,
        owner_id="research-director-1",
        expected_decision_value=1.0,
        budget=budget,
        max_team_count=3,
        max_tree_depth=max_tree_depth,
        hypothesis_families=(family,),
        evidence_binding=binding,
    ).sealed()


def test_research_tree_rejects_duplicate_active_hypothesis_and_excess_depth() -> None:
    programme = _programme(max_tree_depth=1)
    team = ResearchTeam(
        team_id="team-1",
        programme_id=programme.programme_id,
        role="hypothesis_architect",
        member_ids=("researcher-1",),
        compute_limit=10.0,
    ).sealed()
    root = ResearchTreeNode(
        node_id="node-1",
        programme_id=programme.programme_id,
        team_id=team.team_id,
        hypothesis_id="hypothesis-a",
        depth=0,
        compute_cost=1.0,
    ).sealed()
    duplicate = ResearchTreeNode(
        node_id="node-2",
        programme_id=programme.programme_id,
        team_id=team.team_id,
        hypothesis_id="hypothesis-a",
        depth=0,
        compute_cost=1.0,
    ).sealed()

    with pytest.raises(ValidationError, match="duplicate active hypothesis"):
        ResearchTree(
            tree_id="tree-1",
            programme=programme,
            teams=(team,),
            nodes=(root, duplicate),
        )

    too_deep = ResearchTreeNode(
        node_id="node-3",
        programme_id=programme.programme_id,
        team_id=team.team_id,
        hypothesis_id="hypothesis-b",
        parent_node_id=root.node_id,
        depth=2,
        compute_cost=1.0,
    ).sealed()
    with pytest.raises(ValidationError, match="tree depth"):
        ResearchTree(
            tree_id="tree-1",
            programme=programme,
            teams=(team,),
            nodes=(root, too_deep),
        )

    replication_team = ResearchTeam(
        team_id="replication-team-1",
        programme_id=programme.programme_id,
        role="replication_team",
        member_ids=("replicator-1",),
        compute_limit=10.0,
    ).sealed()
    first_replication = ResearchTreeNode(
        node_id="replication-1",
        programme_id=programme.programme_id,
        team_id=replication_team.team_id,
        hypothesis_id=root.hypothesis_id,
        parent_node_id=root.node_id,
        depth=1,
        compute_cost=1.0,
        node_kind="replication",
        replicates_node_id=root.node_id,
    ).sealed()
    valid_replication_tree = ResearchTree(
        tree_id="tree-valid-replication",
        programme=programme,
        teams=(team, replication_team),
        nodes=(root, first_replication),
    ).sealed()
    assert valid_replication_tree.authority == "candidate_only"

    wrong_role_replication = first_replication.model_copy(
        update={"team_id": team.team_id, "content_hash": None}
    ).sealed()
    with pytest.raises(ValidationError, match="replication team"):
        ResearchTree(
            tree_id="tree-wrong-replication-role",
            programme=programme,
            teams=(team,),
            nodes=(root, wrong_role_replication),
        )
    chained_replication = ResearchTreeNode(
        node_id="replication-2",
        programme_id=programme.programme_id,
        team_id=replication_team.team_id,
        hypothesis_id=root.hypothesis_id,
        parent_node_id=root.node_id,
        depth=1,
        compute_cost=1.0,
        node_kind="replication",
        replicates_node_id=first_replication.node_id,
    ).sealed()
    with pytest.raises(ValidationError, match="original hypothesis node"):
        ResearchTree(
            tree_id="tree-replication-chain",
            programme=programme,
            teams=(team, replication_team),
            nodes=(root, first_replication, chained_replication),
        )


def test_research_tree_rejects_invalid_parent_and_compute_breaches() -> None:
    programme = _programme()
    team = ResearchTeam(
        team_id="team-1",
        programme_id=programme.programme_id,
        role="hypothesis_architect",
        member_ids=("researcher-1",),
        compute_limit=10.0,
    ).sealed()
    orphan = ResearchTreeNode(
        node_id="node-orphan",
        programme_id=programme.programme_id,
        team_id=team.team_id,
        hypothesis_id="hypothesis-a",
        parent_node_id="missing-parent",
        depth=1,
        compute_cost=1.0,
    ).sealed()
    with pytest.raises(ValidationError, match="follow its parent"):
        ResearchTree(
            tree_id="tree-orphan",
            programme=programme,
            teams=(team,),
            nodes=(orphan,),
        )

    root = orphan.model_copy(
        update={
            "node_id": "node-root",
            "parent_node_id": None,
            "depth": 0,
            "content_hash": None,
        }
    ).sealed()
    low_limit_team = team.model_copy(update={"compute_limit": 0.5, "content_hash": None}).sealed()
    with pytest.raises(ValidationError, match="team compute limit"):
        ResearchTree(
            tree_id="tree-team-cost",
            programme=programme,
            teams=(low_limit_team,),
            nodes=(root,),
        )

    second_root = root.model_copy(
        update={
            "node_id": "node-root-2",
            "hypothesis_id": "hypothesis-b",
            "content_hash": None,
        }
    ).sealed()
    first_critique = ResearchCritiqueReceipt(
        critique_id="critique-duplicate",
        node_id=root.node_id,
        reviewer_id="reviewer-1",
        recorded_at=AS_OF + timedelta(minutes=2),
        findings=("Review first root.",),
        evidence_binding=programme.evidence_binding,
    ).sealed()
    second_critique = first_critique.model_copy(
        update={"node_id": second_root.node_id, "content_hash": None}
    ).sealed()
    reviewed_root = root.model_copy(
        update={"critique": first_critique, "content_hash": None}
    ).sealed()
    reviewed_second_root = second_root.model_copy(
        update={"critique": second_critique, "content_hash": None}
    ).sealed()
    with pytest.raises(ValidationError, match="critique IDs"):
        ResearchTree(
            tree_id="tree-duplicate-critique",
            programme=programme,
            teams=(team,),
            nodes=(reviewed_root, reviewed_second_root),
        )

    low_budget = ResearchBudget(
        compute_limit=1.0,
        data_limit=5.0,
        review_limit=3.0,
        total_limit=9.0,
    ).sealed()
    low_budget_programme = programme.model_copy(
        update={"budget": low_budget, "content_hash": None}
    ).sealed()
    with pytest.raises(ValidationError, match="programme compute limit"):
        ResearchTree(
            tree_id="tree-programme-cost",
            programme=low_budget_programme,
            teams=(team,),
            nodes=(root, second_root),
        )


def test_research_tree_requires_recorded_critique_before_plan() -> None:
    programme = _programme()
    hypothesis = programme.hypothesis_families[0].hypotheses[0]
    team = ResearchTeam(
        team_id="team-1",
        programme_id=programme.programme_id,
        role="experiment_designer",
        member_ids=("designer-1",),
        compute_limit=10.0,
    ).sealed()
    node_values = {
        "node_id": "node-1",
        "programme_id": programme.programme_id,
        "team_id": team.team_id,
        "hypothesis_id": hypothesis.hypothesis_id,
        "depth": 0,
        "compute_cost": 1.0,
    }
    node = ResearchTreeNode(**node_values).sealed()
    tree = ResearchTree(
        tree_id="tree-1",
        programme=programme,
        teams=(team,),
        nodes=(node,),
    ).sealed()
    plan = ExperimentPlan(
        experiment_id="experiment-1",
        tree_node_id=node.node_id,
        hypothesis=hypothesis,
        preregistered_at=AS_OF + timedelta(minutes=2),
        evidence_binding=programme.evidence_binding,
        dataset_snapshot_hash=programme.evidence_binding.snapshot.content_hash,
        split_policy_id="split-policy-1",
        metric_ids=("metric-1",),
        baseline_ids=("baseline-1",),
        ablation_ids=("ablation-1",),
        cost_model_id="cost-model-1",
        stop_rules=("stop-rule-1",),
        locked_fields=LOCKED_FIELDS,
        author_id="designer-1",
    ).sealed()

    with pytest.raises(ValueError, match="recorded critique"):
        tree.validate_plan(plan)

    critique = ResearchCritiqueReceipt(
        critique_id="critique-1",
        node_id=node.node_id,
        reviewer_id="reviewer-1",
        recorded_at=AS_OF + timedelta(seconds=90),
        findings=("Baseline choice requires adversarial review.",),
        evidence_binding=programme.evidence_binding,
    ).sealed()
    reviewed_node = ResearchTreeNode(**(node_values | {"critique": critique})).sealed()
    reviewed_tree = ResearchTree(
        tree_id="tree-1",
        programme=programme,
        teams=(team,),
        nodes=(reviewed_node,),
    ).sealed()
    reviewed_tree.validate_plan(plan)

    equal_time_plan = plan.model_copy(
        update={
            "preregistered_at": critique.recorded_at,
            "content_hash": None,
        }
    ).sealed()
    with pytest.raises(ValueError, match="before preregistration"):
        reviewed_tree.validate_plan(equal_time_plan)

    self_review = critique.model_copy(
        update={"reviewer_id": "designer-1", "content_hash": None}
    ).sealed()
    self_reviewed_node = ResearchTreeNode(**(node_values | {"critique": self_review})).sealed()
    self_reviewed_tree = ResearchTree(
        tree_id="tree-self-review",
        programme=programme,
        teams=(team,),
        nodes=(self_reviewed_node,),
    ).sealed()
    with pytest.raises(ValueError, match="review their own"):
        self_reviewed_tree.validate_plan(plan)

    substituted_hypothesis = hypothesis.model_copy(
        update={"statement": "Altered same-ID hypothesis.", "content_hash": None}
    ).sealed()
    substituted_plan = plan.model_copy(
        update={"hypothesis": substituted_hypothesis, "content_hash": None}
    ).sealed()
    with pytest.raises(ValueError, match="programme hypothesis"):
        reviewed_tree.validate_plan(substituted_plan)

    stopped_node = reviewed_node.model_copy(
        update={"status": "stopped", "content_hash": None}
    ).sealed()
    stopped_node_tree = ResearchTree(
        tree_id="tree-stopped-node",
        programme=programme,
        teams=(team,),
        nodes=(stopped_node,),
    ).sealed()
    with pytest.raises(ValueError, match="stopped"):
        stopped_node_tree.validate_plan(plan)

    stopped_programme = programme.model_copy(
        update={"status": "stopped", "content_hash": None}
    ).sealed()
    stopped_programme_tree = ResearchTree(
        tree_id="tree-stopped-programme",
        programme=stopped_programme,
        teams=(team,),
        nodes=(reviewed_node,),
    ).sealed()
    with pytest.raises(ValueError, match="stopped"):
        stopped_programme_tree.validate_plan(plan)


def test_v6_role_grants_deny_omissions_and_capital_critical_tools() -> None:
    capability = "science.programme.plan"
    assert authorize_v6_research_tool("director", capability) == capability

    with pytest.raises(CapabilityDenied, match="not granted"):
        authorize_v6_research_tool("director", "science.fixture.evaluate")
    with pytest.raises(CapabilityDenied, match="not granted"):
        authorize_v6_research_tool("unknown", capability)  # type: ignore[arg-type]
    for forbidden in (
        "broker.submit_order",
        "execution.submit",
        "fund.allocate",
        "promotion.approve",
        "risk.decide",
        "source.direct_http.fetch",
    ):
        with pytest.raises(CapabilityDenied, match="capital-critical"):
            authorize_v6_research_tool("director", forbidden)


def test_research_programme_requires_two_competing_hypotheses() -> None:
    binding = _evidence_binding()
    first = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", binding)
    second = _hypothesis("hypothesis-b", "mechanism-b", "hypothesis-a", binding)
    family = HypothesisFamily(
        family_id="family-1",
        programme_id="programme-1",
        hypotheses=(first, second),
    ).sealed()
    budget = ResearchBudget(
        compute_limit=10.0,
        data_limit=5.0,
        review_limit=3.0,
        total_limit=18.0,
    ).sealed()

    programme = ResearchProgramme(
        programme_id="programme-1",
        mandate="Test competing candidate mechanisms.",
        as_of=AS_OF,
        owner_id="research-director-1",
        expected_decision_value=1.0,
        budget=budget,
        max_team_count=3,
        max_tree_depth=2,
        hypothesis_families=(family,),
        evidence_binding=binding,
    ).sealed()
    assert programme.authority == "candidate_only"
    assert programme.release_disposition == "engineering_only"

    one_hypothesis_family = HypothesisFamily.model_construct(
        family_id="family-1",
        programme_id="programme-1",
        hypotheses=(first,),
        content_hash=None,
    )
    with pytest.raises(ValidationError, match="at least two competing hypotheses"):
        ResearchProgramme(
            programme_id="programme-1",
            mandate="Invalid single-hypothesis programme.",
            as_of=AS_OF,
            owner_id="research-director-1",
            expected_decision_value=1.0,
            budget=budget,
            max_team_count=3,
            max_tree_depth=2,
            hypothesis_families=(one_hypothesis_family,),
            evidence_binding=binding,
        )


def test_research_programme_rejects_hypothesis_evidence_outside_programme_binding() -> None:
    programme_binding = _evidence_binding()
    future_binding = _evidence_binding(as_of=AS_OF + timedelta(days=1))
    first = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", future_binding)
    second = _hypothesis("hypothesis-b", "mechanism-b", "hypothesis-a", future_binding)
    family = HypothesisFamily(
        family_id="family-1",
        programme_id="programme-1",
        hypotheses=(first, second),
    ).sealed()
    budget = ResearchBudget(
        compute_limit=1.0,
        data_limit=1.0,
        review_limit=1.0,
        total_limit=3.0,
    ).sealed()

    with pytest.raises(ValidationError, match="programme evidence binding"):
        ResearchProgramme(
            programme_id="programme-1",
            mandate="Reject substituted hypothesis evidence.",
            as_of=AS_OF,
            owner_id="research-director-1",
            expected_decision_value=1.0,
            budget=budget,
            max_team_count=2,
            max_tree_depth=1,
            hypothesis_families=(family,),
            evidence_binding=programme_binding,
        )


def test_research_evidence_binding_rejects_future_or_unretained_provenance() -> None:
    valid = _evidence_binding()
    assert valid.content_hash is not None

    with pytest.raises(ValidationError, match="available after research cutoff"):
        _evidence_binding(source_available_at=AS_OF + timedelta(seconds=1))

    with pytest.raises(ValidationError, match="retained receipt"):
        _evidence_binding(retained_hash="f" * 64)


def test_experiment_plan_requires_locked_preregistration_surface() -> None:
    binding = _evidence_binding()
    hypothesis = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", binding)
    values = {
        "experiment_id": "experiment-1",
        "tree_node_id": "node-1",
        "hypothesis": hypothesis,
        "preregistered_at": AS_OF + timedelta(minutes=2),
        "evidence_binding": binding,
        "dataset_snapshot_hash": binding.snapshot.content_hash,
        "split_policy_id": "split-policy-1",
        "metric_ids": ("metric-1",),
        "baseline_ids": ("baseline-1",),
        "ablation_ids": ("ablation-1",),
        "cost_model_id": "cost-model-1",
        "stop_rules": ("stop-rule-1",),
        "locked_fields": LOCKED_FIELDS,
        "author_id": "experiment-designer-1",
    }

    plan = ExperimentPlan(**values).sealed()
    assert plan.content_hash is not None
    assert plan.authority == "candidate_only"

    with pytest.raises(ValidationError, match="locked fields"):
        ExperimentPlan(**(values | {"locked_fields": LOCKED_FIELDS[:-1]}))
    with pytest.raises(ValidationError, match="snapshot hash"):
        ExperimentPlan(**(values | {"dataset_snapshot_hash": "f" * 64}))
    with pytest.raises(ValidationError, match="before its evidence cutoff"):
        ExperimentPlan(**(values | {"preregistered_at": AS_OF - timedelta(seconds=1)}))


def test_novelty_report_is_bound_to_hypothesis_and_pit_evidence() -> None:
    binding = _evidence_binding()
    hypothesis = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", binding)
    values = {
        "novelty_report_id": "novelty-1",
        "hypothesis": hypothesis,
        "assessed_at": AS_OF + timedelta(minutes=1),
        "evidence_binding": binding,
        "prior_experiment_ids": ("experiment-prior-1",),
        "surfaced_negative_result_ids": (),
        "limitations": ("Internal records only; no external novelty claim.",),
        "auditor_id": "novelty-auditor-1",
    }

    report = NoveltyReport(**values).sealed()
    assert report.calibration_status == "not_calibrated"
    assert report.novelty_status == "not_established"

    with pytest.raises(ValidationError, match="before its evidence cutoff"):
        NoveltyReport(**(values | {"assessed_at": AS_OF - timedelta(seconds=1)}))
    with pytest.raises(ValidationError, match="evidence must match"):
        other_binding = _evidence_binding(source_available_at=AS_OF - timedelta(days=2))
        NoveltyReport(**(values | {"evidence_binding": other_binding}))


def test_research_lifecycle_records_cannot_predate_retained_receipt() -> None:
    binding = _evidence_binding()
    hypothesis = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", binding)
    before_receipt = binding.original_receipt.recorded_at - timedelta(seconds=1)

    with pytest.raises(ValidationError, match="retained receipt"):
        NoveltyReport(
            novelty_report_id="novelty-1",
            hypothesis=hypothesis,
            assessed_at=before_receipt,
            evidence_binding=binding,
            limitations=("Internal evidence only.",),
            auditor_id="novelty-auditor-1",
        )
    with pytest.raises(ValidationError, match="retained receipt"):
        ExperimentPlan(
            experiment_id="experiment-1",
            tree_node_id="node-1",
            hypothesis=hypothesis,
            preregistered_at=before_receipt,
            evidence_binding=binding,
            dataset_snapshot_hash=binding.snapshot.content_hash,
            split_policy_id="split-policy-1",
            metric_ids=("metric-1",),
            baseline_ids=("baseline-1",),
            ablation_ids=("ablation-1",),
            cost_model_id="cost-model-1",
            stop_rules=("stop-rule-1",),
            locked_fields=LOCKED_FIELDS,
            author_id="experiment-designer-1",
        )


def test_v6_science_contracts_are_public_and_model_copy_fail_closed() -> None:
    from aegis import research_lab

    for name in (
        "ExperimentPlan",
        "Hypothesis",
        "HypothesisFamily",
        "NoveltyReport",
        "ResearchArtifactReceiptReference",
        "ResearchBudget",
        "ResearchCritiqueReceipt",
        "ResearchEvidenceBinding",
        "ResearchProgramme",
        "ResearchTeam",
        "ResearchTree",
        "ResearchTreeNode",
        "V6_ROLE_TOOL_GRANTS",
        "authorize_v6_research_tool",
    ):
        assert getattr(research_lab, name)

    binding = _evidence_binding()
    with pytest.raises(ValueError, match="unknown fields"):
        binding.model_copy(update={"unexpected": "value"})
    with pytest.raises(ValidationError, match="content hash mismatch"):
        binding.model_copy(update={"binding_id": "replacement-binding"})
