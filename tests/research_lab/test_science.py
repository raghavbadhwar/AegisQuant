from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aegis.contracts import canonical_sha256
from aegis.reporting.traceability import SnapshotReference, SourceProvenanceReference
from aegis.research_lab.science import (
    ExperimentPlan,
    Hypothesis,
    HypothesisFamily,
    NoveltyReport,
    ResearchArtifactReceiptReference,
    ResearchBudget,
    ResearchEvidenceBinding,
    ResearchProgramme,
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
        "ResearchEvidenceBinding",
        "ResearchProgramme",
    ):
        assert getattr(research_lab, name)

    binding = _evidence_binding()
    with pytest.raises(ValueError, match="unknown fields"):
        binding.model_copy(update={"unexpected": "value"})
    with pytest.raises(ValidationError, match="content hash mismatch"):
        binding.model_copy(update={"binding_id": "replacement-binding"})
