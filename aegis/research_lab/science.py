"""Candidate-only v6 research institution contracts; no action authority."""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel
from aegis.reporting.traceability import SnapshotReference, SourceProvenanceReference

_SHA256 = r"^[0-9a-f]{64}$"
_PLAN_LOCKED_FIELDS = frozenset(
    {
        "dataset_snapshot_hash",
        "split_policy_id",
        "metric_ids",
        "baseline_ids",
        "ablation_ids",
        "cost_model_id",
        "stop_rules",
    }
)


class _SealedScienceModel(CandidateContractModel):
    content_hash: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def has_valid_content_hash(self) -> Self:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("v6 research contract content hash mismatch")
        return self

    def sealed(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = type(self).model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class ResearchArtifactReceiptReference(_SealedScienceModel):
    """Reference to a separately retained original research-artifact receipt."""

    receipt_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    artifact_content_hash: str = Field(pattern=_SHA256)
    recorded_at: AwareDatetime


class ResearchEvidenceBinding(_SealedScienceModel):
    """PIT-safe evidence/snapshot binding with a retained original receipt reference."""

    binding_id: str = Field(min_length=1)
    as_of: AwareDatetime
    source_provenance: tuple[SourceProvenanceReference, ...] = Field(min_length=1)
    snapshot: SnapshotReference
    original_receipt: ResearchArtifactReceiptReference

    @model_validator(mode="after")
    def binds_pit_sources_snapshot_and_receipt(self) -> ResearchEvidenceBinding:
        sources = tuple(
            SourceProvenanceReference.model_validate(source.model_dump(mode="json"))
            for source in self.source_provenance
        )
        snapshot = SnapshotReference.model_validate(self.snapshot.model_dump(mode="json"))
        receipt = ResearchArtifactReceiptReference.model_validate(
            self.original_receipt.model_dump(mode="json")
        )
        source_ids = [source.source_id for source in sources]
        artifact_ids = [source.artifact_id for source in sources]
        if len(source_ids) != len(set(source_ids)) or len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("research evidence source and artifact IDs must be unique")
        if any(source.available_at > self.as_of for source in sources):
            raise ValueError("research evidence source is available after research cutoff")
        if snapshot.as_of > self.as_of:
            raise ValueError("research evidence snapshot is after research cutoff")
        if receipt.content_hash is None:
            raise ValueError("research evidence requires a sealed retained receipt reference")
        artifact_hash = canonical_sha256(
            {
                "as_of": self.as_of,
                "source_provenance": sources,
                "snapshot": snapshot,
            }
        )
        if (
            receipt.artifact_id != self.binding_id
            or receipt.artifact_content_hash != artifact_hash
            or receipt.recorded_at < self.as_of
        ):
            raise ValueError("research evidence binding does not match the retained receipt")
        return self


class ResearchBudget(_SealedScienceModel):
    """Finite research-unit limits; this record cannot spend or authorize resources."""

    compute_limit: float = Field(ge=0.0, allow_inf_nan=False)
    data_limit: float = Field(ge=0.0, allow_inf_nan=False)
    review_limit: float = Field(ge=0.0, allow_inf_nan=False)
    total_limit: float = Field(ge=0.0, allow_inf_nan=False)
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def total_reconciles(self) -> ResearchBudget:
        expected = self.compute_limit + self.data_limit + self.review_limit
        if not math.isclose(self.total_limit, expected, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("research budget total must reconcile to its component limits")
        return self


class Hypothesis(_SealedScienceModel):
    """One evidence-bound, falsifiable candidate mechanism hypothesis."""

    hypothesis_id: str = Field(min_length=1)
    programme_id: str = Field(min_length=1)
    mechanism_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    falsifiable_predictions: tuple[str, ...] = Field(min_length=1)
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    known_failure_condition: str = Field(min_length=1)
    competes_with: tuple[str, ...] = Field(min_length=1)
    proposer_id: str = Field(min_length=1)
    evidence_binding: ResearchEvidenceBinding
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def has_unique_competition_and_sealed_evidence(self) -> Hypothesis:
        evidence = ResearchEvidenceBinding.model_validate(
            self.evidence_binding.model_dump(mode="json")
        )
        if evidence.content_hash is None:
            raise ValueError("hypothesis requires sealed research evidence")
        if len(self.falsifiable_predictions) != len(set(self.falsifiable_predictions)):
            raise ValueError("hypothesis predictions must be unique")
        if len(self.assumption_ids) != len(set(self.assumption_ids)):
            raise ValueError("hypothesis assumptions must be unique")
        if len(self.competes_with) != len(set(self.competes_with)):
            raise ValueError("hypothesis competitor IDs must be unique")
        if self.hypothesis_id in self.competes_with:
            raise ValueError("hypothesis cannot compete with itself")
        return self


class HypothesisFamily(_SealedScienceModel):
    """A sealed set of explicitly competing candidate hypotheses."""

    family_id: str = Field(min_length=1)
    programme_id: str = Field(min_length=1)
    hypotheses: tuple[Hypothesis, ...]

    @model_validator(mode="after")
    def has_two_or_more_mutual_competitors(self) -> HypothesisFamily:
        hypotheses = tuple(
            Hypothesis.model_validate(hypothesis.model_dump(mode="json"))
            for hypothesis in self.hypotheses
        )
        if len(hypotheses) < 2:
            raise ValueError("hypothesis family requires at least two competing hypotheses")
        by_id = {hypothesis.hypothesis_id: hypothesis for hypothesis in hypotheses}
        if len(by_id) != len(hypotheses):
            raise ValueError("hypothesis family IDs must be unique")
        if any(hypothesis.programme_id != self.programme_id for hypothesis in hypotheses):
            raise ValueError("hypothesis family programme IDs must match")
        if any(hypothesis.content_hash is None for hypothesis in hypotheses):
            raise ValueError("hypothesis family requires sealed hypotheses")
        for hypothesis in hypotheses:
            for competitor_id in hypothesis.competes_with:
                competitor = by_id.get(competitor_id)
                if competitor is None or hypothesis.hypothesis_id not in competitor.competes_with:
                    raise ValueError("hypothesis competition must be mutual within the family")
        return self


class NoveltyReport(_SealedScienceModel):
    """Internal-prior audit that cannot assert external or calibrated novelty."""

    novelty_report_id: str = Field(min_length=1)
    hypothesis: Hypothesis
    assessed_at: AwareDatetime
    evidence_binding: ResearchEvidenceBinding
    prior_experiment_ids: tuple[str, ...] = ()
    surfaced_negative_result_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = Field(min_length=1)
    auditor_id: str = Field(min_length=1)
    novelty_status: Literal["not_established"] = "not_established"
    calibration_status: Literal["not_calibrated"] = "not_calibrated"
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def binds_hypothesis_evidence_and_internal_scope(self) -> NoveltyReport:
        hypothesis = Hypothesis.model_validate(self.hypothesis.model_dump(mode="json"))
        evidence = ResearchEvidenceBinding.model_validate(
            self.evidence_binding.model_dump(mode="json")
        )
        if hypothesis.content_hash is None or evidence.content_hash is None:
            raise ValueError("novelty report requires sealed hypothesis and evidence")
        if hypothesis.evidence_binding.content_hash != evidence.content_hash:
            raise ValueError("novelty report evidence must match its hypothesis")
        if self.assessed_at < evidence.as_of:
            raise ValueError("novelty report cannot be assessed before its evidence cutoff")
        if self.assessed_at < evidence.original_receipt.recorded_at:
            raise ValueError("novelty report cannot predate its retained receipt")
        for name, values in (
            ("prior experiment", self.prior_experiment_ids),
            ("negative result", self.surfaced_negative_result_ids),
            ("limitation", self.limitations),
        ):
            if len(values) != len(set(values)) or any(not value for value in values):
                raise ValueError(f"novelty report {name} values must be unique and non-empty")
        return self


class ExperimentPlan(_SealedScienceModel):
    """Immutable candidate preregistration; it cannot execute an experiment."""

    experiment_id: str = Field(min_length=1)
    tree_node_id: str = Field(min_length=1)
    hypothesis: Hypothesis
    preregistered_at: AwareDatetime
    evidence_binding: ResearchEvidenceBinding
    dataset_snapshot_hash: str = Field(pattern=_SHA256)
    split_policy_id: str = Field(min_length=1)
    metric_ids: tuple[str, ...] = Field(min_length=1)
    baseline_ids: tuple[str, ...] = Field(min_length=1)
    ablation_ids: tuple[str, ...] = Field(min_length=1)
    cost_model_id: str = Field(min_length=1)
    stop_rules: tuple[str, ...] = Field(min_length=1)
    locked_fields: tuple[str, ...] = Field(min_length=1)
    author_id: str = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def binds_sealed_hypothesis_evidence_and_locked_surface(self) -> ExperimentPlan:
        hypothesis = Hypothesis.model_validate(self.hypothesis.model_dump(mode="json"))
        evidence = ResearchEvidenceBinding.model_validate(
            self.evidence_binding.model_dump(mode="json")
        )
        if hypothesis.content_hash is None or evidence.content_hash is None:
            raise ValueError("experiment plan requires sealed hypothesis and evidence")
        if hypothesis.evidence_binding.content_hash != evidence.content_hash:
            raise ValueError("experiment plan evidence must match its hypothesis")
        if self.dataset_snapshot_hash != evidence.snapshot.content_hash:
            raise ValueError("experiment plan snapshot hash must match its evidence binding")
        if self.preregistered_at < evidence.as_of:
            raise ValueError("experiment plan cannot be preregistered before its evidence cutoff")
        if self.preregistered_at < evidence.original_receipt.recorded_at:
            raise ValueError("experiment plan cannot predate its retained receipt")
        if set(self.locked_fields) != _PLAN_LOCKED_FIELDS or len(self.locked_fields) != len(
            _PLAN_LOCKED_FIELDS
        ):
            raise ValueError("experiment plan locked fields must match the governed surface")
        for name, values in (
            ("metric", self.metric_ids),
            ("baseline", self.baseline_ids),
            ("ablation", self.ablation_ids),
            ("stop rule", self.stop_rules),
        ):
            if len(values) != len(set(values)) or any(not value for value in values):
                raise ValueError(f"experiment plan {name} IDs must be unique and non-empty")
        return self


class ResearchProgramme(_SealedScienceModel):
    """Candidate-only research programme; it cannot initiate work or spending."""

    programme_id: str = Field(min_length=1)
    mandate: str = Field(min_length=1)
    as_of: AwareDatetime
    owner_id: str = Field(min_length=1)
    expected_decision_value: float = Field(ge=0.0, allow_inf_nan=False)
    budget: ResearchBudget
    max_team_count: int = Field(ge=1)
    max_tree_depth: int = Field(ge=1)
    hypothesis_families: tuple[HypothesisFamily, ...] = Field(min_length=1)
    evidence_binding: ResearchEvidenceBinding
    status: Literal["planned", "active", "stopped"] = "planned"
    authority: Literal["candidate_only"] = "candidate_only"
    release_disposition: Literal["engineering_only"] = "engineering_only"

    @model_validator(mode="after")
    def revalidates_bound_graph_and_budget(self) -> ResearchProgramme:
        budget = ResearchBudget.model_validate(self.budget.model_dump(mode="json"))
        evidence = ResearchEvidenceBinding.model_validate(
            self.evidence_binding.model_dump(mode="json")
        )
        families = tuple(
            HypothesisFamily.model_validate(family.model_dump(mode="json"))
            for family in self.hypothesis_families
        )
        if budget.content_hash is None or evidence.content_hash is None:
            raise ValueError("research programme requires sealed budget and evidence")
        if evidence.as_of != self.as_of:
            raise ValueError("research programme cutoff must match its evidence binding")
        family_ids = [family.family_id for family in families]
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("research programme family IDs must be unique")
        if any(
            family.programme_id != self.programme_id or family.content_hash is None
            for family in families
        ):
            raise ValueError("research programme requires sealed same-programme families")
        if any(
            hypothesis.evidence_binding.content_hash != evidence.content_hash
            for family in families
            for hypothesis in family.hypotheses
        ):
            raise ValueError("hypothesis must match the programme evidence binding")
        hypothesis_ids = [
            hypothesis.hypothesis_id for family in families for hypothesis in family.hypotheses
        ]
        if len(hypothesis_ids) < 2:
            raise ValueError("research programme requires at least two competing hypotheses")
        if len(hypothesis_ids) != len(set(hypothesis_ids)):
            raise ValueError("research programme hypothesis IDs must be globally unique")
        return self
