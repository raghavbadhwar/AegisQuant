"""Candidate-only v6 research institution contracts; no action authority."""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal, Self

from pydantic import AwareDatetime, Field, ValidationInfo, model_validator

from aegis.contracts import ExperimentRecord, canonical_sha256
from aegis.contracts._base import CandidateContractModel
from aegis.harness.capability_broker import CapabilityDenied
from aegis.reporting.traceability import SnapshotReference, SourceProvenanceReference
from aegis.research_lab.experiments import ExperimentLedger

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
        validated = type(self).model_validate_json(self.model_dump_json(exclude={"content_hash"}))
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


ResearchRole = Literal[
    "director",
    "hypothesis_architect",
    "novelty_auditor",
    "experiment_designer",
    "quant_research_engineer",
    "statistician",
    "replication_team",
    "adversarial_reviewer",
    "claim_verifier",
    "archivist",
]

V6_ROLE_TOOL_GRANTS: Mapping[ResearchRole, frozenset[str]] = MappingProxyType(
    {
        "director": frozenset({"science.programme.plan", "science.portfolio.rank"}),
        "hypothesis_architect": frozenset({"science.hypothesis.propose", "science.tree.propose"}),
        "novelty_auditor": frozenset({"science.archive.search", "science.novelty.record"}),
        "experiment_designer": frozenset({"science.experiment.preregister"}),
        "quant_research_engineer": frozenset({"science.fixture.evaluate"}),
        "statistician": frozenset({"science.experiment.review"}),
        "replication_team": frozenset({"science.replication.record"}),
        "adversarial_reviewer": frozenset({"science.review.adversarial"}),
        "claim_verifier": frozenset({"science.claim.verify"}),
        "archivist": frozenset({"science.archive.record", "science.postmortem.record"}),
    }
)
_V6_FORBIDDEN_CAPABILITY_PREFIXES = (
    "broker.",
    "execution.",
    "fund.",
    "promotion.",
    "risk.",
    "source.",
)


def authorize_v6_research_tool(role: ResearchRole, capability: str) -> str:
    """Authorize one deterministic in-process research capability, never an external tool."""

    if capability.startswith(_V6_FORBIDDEN_CAPABILITY_PREFIXES):
        raise CapabilityDenied("v6 roles cannot access capital-critical or source capabilities")
    if capability not in V6_ROLE_TOOL_GRANTS.get(role, frozenset()):
        raise CapabilityDenied("v6 research capability is not granted to this role")
    return capability


class ResearchTeam(_SealedScienceModel):
    """A bounded candidate-only team identity; it cannot start work."""

    team_id: str = Field(min_length=1)
    programme_id: str = Field(min_length=1)
    role: ResearchRole
    member_ids: tuple[str, ...] = Field(min_length=1)
    compute_limit: float = Field(ge=0.0, allow_inf_nan=False)
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def has_unique_members(self) -> ResearchTeam:
        if len(self.member_ids) != len(set(self.member_ids)) or any(
            not member_id for member_id in self.member_ids
        ):
            raise ValueError("research team member IDs must be unique and non-empty")
        return self


class ResearchCritiqueReceipt(_SealedScienceModel):
    """Evidence-bound critique recorded before a research plan may use a node."""

    critique_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    recorded_at: AwareDatetime
    findings: tuple[str, ...] = Field(min_length=1)
    evidence_binding: ResearchEvidenceBinding
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def binds_sealed_evidence_and_lifecycle(self) -> ResearchCritiqueReceipt:
        evidence = ResearchEvidenceBinding.model_validate(
            self.evidence_binding.model_dump(mode="json")
        )
        if evidence.content_hash is None:
            raise ValueError("research critique requires sealed evidence")
        if self.recorded_at < evidence.original_receipt.recorded_at:
            raise ValueError("research critique cannot predate its retained receipt")
        if len(self.findings) != len(set(self.findings)) or any(
            not finding for finding in self.findings
        ):
            raise ValueError("research critique findings must be unique and non-empty")
        return self


class ResearchTreeNode(_SealedScienceModel):
    """One bounded hypothesis or replication node in a progressive research tree."""

    node_id: str = Field(min_length=1)
    programme_id: str = Field(min_length=1)
    team_id: str = Field(min_length=1)
    hypothesis_id: str = Field(min_length=1)
    parent_node_id: str | None = Field(default=None, min_length=1)
    depth: int = Field(ge=0)
    compute_cost: float = Field(ge=0.0, allow_inf_nan=False)
    node_kind: Literal["hypothesis", "replication"] = "hypothesis"
    replicates_node_id: str | None = Field(default=None, min_length=1)
    critique: ResearchCritiqueReceipt | None = None
    status: Literal["active", "stopped"] = "active"
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def has_consistent_replication_identity(self) -> ResearchTreeNode:
        if (self.node_kind == "replication") != (self.replicates_node_id is not None):
            raise ValueError("replication nodes require exactly one original node reference")
        if self.replicates_node_id == self.node_id:
            raise ValueError("research tree node cannot replicate itself")
        if self.critique is not None:
            critique = ResearchCritiqueReceipt.model_validate(self.critique.model_dump(mode="json"))
            if critique.content_hash is None or critique.node_id != self.node_id:
                raise ValueError("research tree node requires a sealed matching critique")
        return self


class ResearchTree(_SealedScienceModel):
    """Sealed bounded research tree; validation grants no execution authority."""

    tree_id: str = Field(min_length=1)
    programme: ResearchProgramme
    teams: tuple[ResearchTeam, ...] = Field(min_length=1)
    nodes: tuple[ResearchTreeNode, ...] = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def enforces_team_depth_cost_and_replication_bounds(self) -> ResearchTree:
        programme = ResearchProgramme.model_validate(self.programme.model_dump(mode="json"))
        teams = tuple(
            ResearchTeam.model_validate(team.model_dump(mode="json")) for team in self.teams
        )
        nodes = tuple(
            ResearchTreeNode.model_validate(node.model_dump(mode="json")) for node in self.nodes
        )
        if programme.content_hash is None or any(team.content_hash is None for team in teams):
            raise ValueError("research tree requires a sealed programme and teams")
        if any(node.content_hash is None for node in nodes):
            raise ValueError("research tree requires sealed nodes")
        team_by_id = {team.team_id: team for team in teams}
        node_by_id = {node.node_id: node for node in nodes}
        if len(team_by_id) != len(teams) or len(node_by_id) != len(nodes):
            raise ValueError("research tree team and node IDs must be unique")
        critique_ids = [node.critique.critique_id for node in nodes if node.critique is not None]
        if len(critique_ids) != len(set(critique_ids)):
            raise ValueError("research tree critique IDs must be unique")
        if len(teams) > programme.max_team_count:
            raise ValueError("research tree exceeds programme team count")
        if any(team.programme_id != programme.programme_id for team in teams):
            raise ValueError("research tree team programme IDs must match")
        if any(
            node.programme_id != programme.programme_id or node.team_id not in team_by_id
            for node in nodes
        ):
            raise ValueError("research tree nodes require a known same-programme team")
        if any(
            node.critique is not None
            and node.critique.evidence_binding.content_hash
            != programme.evidence_binding.content_hash
            for node in nodes
        ):
            raise ValueError("research tree critique must match programme evidence")
        if any(node.depth > programme.max_tree_depth for node in nodes):
            raise ValueError("research tree depth exceeds the programme limit")

        hypothesis_ids = {
            hypothesis.hypothesis_id
            for family in programme.hypothesis_families
            for hypothesis in family.hypotheses
        }
        if any(node.hypothesis_id not in hypothesis_ids for node in nodes):
            raise ValueError("research tree node requires a programme hypothesis")
        for node in nodes:
            if node.parent_node_id is None:
                if node.depth != 0:
                    raise ValueError("research tree root depth must be zero")
            else:
                parent = node_by_id.get(node.parent_node_id)
                if parent is None or node.depth != parent.depth + 1:
                    raise ValueError("research tree child depth must follow its parent")

        active_nodes = tuple(node for node in nodes if node.status == "active")
        if sum(node.compute_cost for node in active_nodes) > programme.budget.compute_limit:
            raise ValueError("research tree exceeds programme compute limit")
        for team in teams:
            if (
                sum(node.compute_cost for node in active_nodes if node.team_id == team.team_id)
                > team.compute_limit
            ):
                raise ValueError("research tree exceeds team compute limit")

        active_by_hypothesis: dict[str, list[ResearchTreeNode]] = {}
        for node in active_nodes:
            active_by_hypothesis.setdefault(node.hypothesis_id, []).append(node)
        for same_hypothesis in active_by_hypothesis.values():
            originals = [node for node in same_hypothesis if node.node_kind == "hypothesis"]
            if len(originals) > 1:
                raise ValueError("research tree contains a duplicate active hypothesis")
            for node in same_hypothesis:
                if node.node_kind != "replication":
                    continue
                original = node_by_id.get(node.replicates_node_id or "")
                if (
                    original is None
                    or original.hypothesis_id != node.hypothesis_id
                    or original.node_kind != "hypothesis"
                ):
                    raise ValueError("replication must reference its original hypothesis node")
                if team_by_id[node.team_id].role != "replication_team":
                    raise ValueError("duplicate active hypothesis requires a replication team")
        return self

    def validate_plan(self, plan: ExperimentPlan) -> None:
        tree = type(self).model_validate(self.model_dump(mode="json"))
        validated_plan = ExperimentPlan.model_validate(plan.model_dump(mode="json"))
        if tree.content_hash is None or validated_plan.content_hash is None:
            raise ValueError("research plan validation requires sealed records")
        node = next(
            (
                candidate
                for candidate in tree.nodes
                if candidate.node_id == validated_plan.tree_node_id
            ),
            None,
        )
        if node is None or node.hypothesis_id != validated_plan.hypothesis.hypothesis_id:
            raise ValueError("research plan must match a tree node hypothesis")
        if tree.programme.status == "stopped" or node.status == "stopped":
            raise ValueError("research plan cannot use a stopped programme or tree node")
        programme_hypothesis = next(
            hypothesis
            for family in tree.programme.hypothesis_families
            for hypothesis in family.hypotheses
            if hypothesis.hypothesis_id == node.hypothesis_id
        )
        if programme_hypothesis.content_hash != validated_plan.hypothesis.content_hash:
            raise ValueError("research plan must match the sealed programme hypothesis")
        if (
            validated_plan.evidence_binding.content_hash
            != tree.programme.evidence_binding.content_hash
        ):
            raise ValueError("research plan must match programme evidence")
        if node.critique is None or node.critique.recorded_at >= validated_plan.preregistered_at:
            raise ValueError("research plan requires a recorded critique before preregistration")
        team = next(team for team in tree.teams if team.team_id == node.team_id)
        if (
            node.critique.reviewer_id in team.member_ids
            or node.critique.reviewer_id == validated_plan.author_id
        ):
            raise ValueError("research team members cannot review their own output")


class ExperimentRun(_SealedScienceModel):
    """One deterministic registered-fixture run with no general execution authority."""

    experiment_id: str = Field(min_length=1)
    programme_id: str = Field(min_length=1)
    plan: ExperimentPlan
    executor_id: str = Field(min_length=1)
    executor_kind: Literal["registered_fixture"] = "registered_fixture"
    code_revision: str = Field(min_length=1)
    tree_hash: str = Field(pattern=_SHA256)
    data_snapshot_hash: str = Field(pattern=_SHA256)
    seed: int = Field(ge=0)
    parameter_draw_hash: str = Field(pattern=_SHA256)
    result_content_hash: str = Field(pattern=_SHA256)
    trial_number: int = Field(gt=0)
    status: Literal["passed", "failed", "rejected"]
    started_at: AwareDatetime
    completed_at: AwareDatetime
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def binds_plan_data_and_lifecycle(self) -> ExperimentRun:
        plan = ExperimentPlan.model_validate(self.plan.model_dump(mode="json"))
        if plan.content_hash is None:
            raise ValueError("experiment run requires a sealed plan")
        if self.experiment_id != plan.experiment_id:
            raise ValueError("experiment run ID must match its plan")
        if self.data_snapshot_hash != plan.dataset_snapshot_hash:
            raise ValueError("experiment run data snapshot must match its plan")
        if self.started_at <= plan.preregistered_at:
            raise ValueError("experiment run must start after preregistration")
        if self.completed_at < self.started_at:
            raise ValueError("experiment run completion cannot precede its start")
        return self


class ExperimentRunAbstention(_SealedScienceModel):
    """Typed no-write result for an unavailable registered-fixture executor."""

    experiment_id: str = Field(min_length=1)
    executor_id: str = Field(min_length=1)
    requested_run_hash: str = Field(pattern=_SHA256)
    plan_hash: str = Field(pattern=_SHA256)
    tree_hash: str = Field(pattern=_SHA256)
    reason: Literal["unsupported_or_unavailable_executor"] = "unsupported_or_unavailable_executor"
    authority: Literal["candidate_only"] = "candidate_only"


_REGISTERED_V6_FIXTURE_EXECUTORS = frozenset({"registered-fixture-1"})


def _experiment_record(run: ExperimentRun) -> ExperimentRecord:
    if run.content_hash is None:
        raise ValueError("experiment record requires a sealed v6 run")
    payload: dict[str, Any] = {
        "experiment_id": run.experiment_id,
        "candidate_id": f"v6:{run.programme_id}",
        "hypothesis_id": run.plan.hypothesis.hypothesis_id,
        "parent_experiment_id": None,
        "code_revision": run.code_revision,
        "tree_hash": run.tree_hash,
        "data_snapshot_hash": run.data_snapshot_hash,
        "parameters": {
            "v6_run": run.model_dump(mode="json"),
            "v6_run_content_hash": run.content_hash,
        },
        "dependency_versions": {"aegisquant": "v6"},
        "trial_number": run.trial_number,
        "status": run.status,
        "created_at": run.started_at,
    }
    return ExperimentRecord.model_validate(payload | {"content_hash": canonical_sha256(payload)})


def load_experiment_run(record: ExperimentRecord) -> ExperimentRun:
    """Reconstruct and cross-check a sealed v6 run from its ledger envelope."""

    validated_record = ExperimentRecord.model_validate_json(record.model_dump_json())
    parameters = validated_record.parameters
    if set(parameters) != {"v6_run", "v6_run_content_hash"}:
        raise ValueError("experiment record does not contain an exact v6 run payload")
    run_payload = parameters["v6_run"]
    run_hash = parameters["v6_run_content_hash"]
    if not isinstance(run_payload, dict) or not isinstance(run_hash, str):
        raise ValueError("experiment record v6 run payload is malformed")
    run = ExperimentRun.model_validate(run_payload)
    if run.content_hash is None or run.content_hash != run_hash:
        raise ValueError("experiment record v6 run content hash mismatch")
    if (
        validated_record.experiment_id != run.experiment_id
        or validated_record.candidate_id != f"v6:{run.programme_id}"
        or validated_record.hypothesis_id != run.plan.hypothesis.hypothesis_id
        or validated_record.code_revision != run.code_revision
        or validated_record.tree_hash != run.tree_hash
        or validated_record.data_snapshot_hash != run.data_snapshot_hash
        or validated_record.trial_number != run.trial_number
        or validated_record.status != run.status
        or validated_record.created_at != run.started_at
        or validated_record.dependency_versions != {"aegisquant": "v6"}
    ):
        raise ValueError("experiment record envelope does not match its v6 run")
    return run


def record_experiment_run(
    ledger: ExperimentLedger, run: ExperimentRun, tree: ResearchTree
) -> ExperimentRun | ExperimentRunAbstention:
    """Append and verify the exact v6 run before returning it to a caller."""

    validated_run = ExperimentRun.model_validate(run.model_dump(mode="json"))
    validated_tree = ResearchTree.model_validate(tree.model_dump(mode="json"))
    if validated_run.content_hash is None or validated_tree.content_hash is None:
        raise ValueError("experiment recording requires sealed run and tree")
    if (
        validated_run.programme_id != validated_tree.programme.programme_id
        or validated_run.tree_hash != validated_tree.content_hash
    ):
        raise ValueError("experiment run does not match its research tree")
    validated_tree.validate_plan(validated_run.plan)
    if validated_run.executor_id not in _REGISTERED_V6_FIXTURE_EXECUTORS:
        if validated_run.plan.content_hash is None:
            raise ValueError("experiment abstention requires a sealed plan")
        return ExperimentRunAbstention(
            experiment_id=validated_run.experiment_id,
            executor_id=validated_run.executor_id,
            requested_run_hash=validated_run.content_hash,
            plan_hash=validated_run.plan.content_hash,
            tree_hash=validated_tree.content_hash,
        ).sealed()
    ledger.append(_experiment_record(validated_run))
    loaded = load_experiment_run(ledger.get(validated_run.experiment_id))
    if loaded.content_hash != validated_run.content_hash:
        raise ValueError("persisted experiment run does not match submitted content")
    return loaded


class ReplicationRun(_SealedScienceModel):
    """Independent candidate replication bound to one original ledgered run."""

    replication_id: str = Field(min_length=1)
    original_run: ExperimentRun
    original_record: ExperimentRecord
    replication_run: ExperimentRun
    replication_record: ExperimentRecord
    replicator_id: str = Field(min_length=1)
    recorded_at: AwareDatetime
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def binds_independent_same_hypothesis_run(self) -> ReplicationRun:
        original = ExperimentRun.model_validate(self.original_run.model_dump(mode="json"))
        replication = ExperimentRun.model_validate(self.replication_run.model_dump(mode="json"))
        ledgered_original = load_experiment_run(self.original_record)
        ledgered_replication = load_experiment_run(self.replication_record)
        if original.content_hash is None or replication.content_hash is None:
            raise ValueError("replication requires sealed runs")
        if (
            ledgered_original.content_hash != original.content_hash
            or ledgered_replication.content_hash != replication.content_hash
        ):
            raise ValueError("replication requires exact ledger-bound runs")
        if original.experiment_id == replication.experiment_id:
            raise ValueError("replication run must differ from its original run")
        if (
            original.programme_id != replication.programme_id
            or original.plan.hypothesis.content_hash != replication.plan.hypothesis.content_hash
            or original.data_snapshot_hash != replication.data_snapshot_hash
        ):
            raise ValueError("replication must preserve programme, hypothesis, and data identity")
        if self.replicator_id in {
            original.plan.hypothesis.proposer_id,
            original.plan.author_id,
        }:
            raise ValueError("replication requires an independent replicator")
        if replication.plan.author_id != self.replicator_id:
            raise ValueError("replication plan author must be the replicator")
        if self.recorded_at < replication.completed_at:
            raise ValueError("replication cannot be recorded before completion")
        return self


class VerificationPackage(_SealedScienceModel):
    """Bounded independent verification evidence; it grants no promotion authority."""

    package_id: str = Field(min_length=1)
    original_run: ExperimentRun
    original_record: ExperimentRecord
    replications: tuple[ReplicationRun, ...] = ()
    verifier_id: str = Field(min_length=1)
    approver_id: str = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    claim_strength_ceiling: Literal["limited", "verified"]
    verified_at: AwareDatetime
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def enforces_replication_and_identity_separation(self) -> VerificationPackage:
        original = ExperimentRun.model_validate(self.original_run.model_dump(mode="json"))
        ledgered_original = load_experiment_run(self.original_record)
        replications = tuple(
            ReplicationRun.model_validate_json(replication.model_dump_json())
            for replication in self.replications
        )
        if original.content_hash is None or any(item.content_hash is None for item in replications):
            raise ValueError("verification package requires sealed runs and replications")
        if ledgered_original.content_hash != original.content_hash:
            raise ValueError("verification package requires an exact ledger-bound original run")
        if self.claim_strength_ceiling == "verified" and not replications:
            raise ValueError("verified package requires an independent replication")
        if self.claim_strength_ceiling == "verified" and (
            original.status != "passed"
            or any(item.replication_run.status != "passed" for item in replications)
        ):
            raise ValueError("verified package requires passed supporting runs")
        if any(item.original_run.content_hash != original.content_hash for item in replications):
            raise ValueError("verification replication must bind the package original run")
        replication_ids = [item.replication_id for item in replications]
        if len(replication_ids) != len(set(replication_ids)):
            raise ValueError("verification replication IDs must be unique")
        replication_run_hashes = [item.replication_run.content_hash for item in replications]
        if len(replication_run_hashes) != len(set(replication_run_hashes)):
            raise ValueError("verification replication runs must be unique")
        identities = {
            original.plan.hypothesis.proposer_id,
            original.plan.author_id,
            *(item.replicator_id for item in replications),
        }
        if (
            self.verifier_id == self.approver_id
            or self.verifier_id in identities
            or self.approver_id in identities
        ):
            raise ValueError(
                "verification requires proposer, replicator, verifier, approver identity separation"
            )
        if self.verified_at < max(
            (item.recorded_at for item in replications), default=original.completed_at
        ):
            raise ValueError("verification cannot predate its supporting runs")
        if len(self.limitations) != len(set(self.limitations)) or any(
            not limitation for limitation in self.limitations
        ):
            raise ValueError("verification limitations must be unique and non-empty")
        return self


class ResearchClaim(_SealedScienceModel):
    """Candidate claim whose conclusion cannot exceed sealed verification support."""

    claim_id: str = Field(min_length=1)
    package: VerificationPackage | None = None
    status: Literal["candidate", "limited", "verified", "rejected", "abstained"]
    conclusion: str | None = Field(default=None, min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"
    release_disposition: Literal["engineering_only"] = "engineering_only"

    @classmethod
    def verified(
        cls,
        *,
        claim_id: str,
        package: VerificationPackage,
        conclusion: str,
        ledger: ExperimentLedger,
    ) -> ResearchClaim:
        payload = {
            "claim_id": claim_id,
            "package": package,
            "status": "verified",
            "conclusion": conclusion,
        }
        context = {"experiment_ledger": ledger}
        draft = cls.model_validate(payload, context=context)
        content_hash = canonical_sha256(draft.model_dump(mode="json", exclude={"content_hash"}))
        return cls.model_validate(payload | {"content_hash": content_hash}, context=context)

    @model_validator(mode="after")
    def cannot_exceed_verification_support(self, info: ValidationInfo) -> ResearchClaim:
        package = (
            VerificationPackage.model_validate_json(self.package.model_dump_json())
            if self.package is not None
            else None
        )
        if package is not None and package.content_hash is None:
            raise ValueError("research claim requires a sealed verification package")
        if self.status == "verified" and (
            package is None or package.claim_strength_ceiling != "verified"
        ):
            raise ValueError("verified claim requires verified replication support")
        if self.status == "verified":
            ledger = (info.context or {}).get("experiment_ledger")
            if not isinstance(ledger, ExperimentLedger):
                raise ValueError("verified claim requires ledger verification context")
            if package is None:
                raise ValueError("verified claim requires a verification package")
            if ledger.get(package.original_run.experiment_id) != package.original_record:
                raise ValueError("verified claim original run is not included in the ledger")
            for replication in package.replications:
                if (
                    ledger.get(replication.replication_run.experiment_id)
                    != replication.replication_record
                ):
                    raise ValueError("verified claim replication is not included in the ledger")
        if self.status == "abstained" and self.conclusion is not None:
            raise ValueError("abstained research claim cannot contain a conclusion")
        if self.conclusion is not None and package is None:
            raise ValueError("research conclusion requires a sealed verification package")
        if self.status in {"limited", "verified"} and self.conclusion is None:
            raise ValueError("supported research claim requires an explicit conclusion")
        return self


class NegativeResult(_SealedScienceModel):
    """Preserved rejected or inconclusive result for deterministic prior-failure surfacing."""

    negative_result_id: str = Field(min_length=1)
    run: ExperimentRun
    disposition: Literal["rejected", "inconclusive"]
    category: Literal["causal", "economic", "operational"]
    reason: str = Field(min_length=1)
    reopen_condition: str = Field(min_length=1)
    mechanism_id: str = Field(min_length=1)
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    recorded_at: AwareDatetime
    evidence_binding: ResearchEvidenceBinding
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def binds_run_hypothesis_and_evidence(self) -> NegativeResult:
        run = ExperimentRun.model_validate(self.run.model_dump(mode="json"))
        evidence = ResearchEvidenceBinding.model_validate(
            self.evidence_binding.model_dump(mode="json")
        )
        if run.content_hash is None or evidence.content_hash is None:
            raise ValueError("negative result requires sealed run and evidence")
        hypothesis = run.plan.hypothesis
        if (
            self.mechanism_id != hypothesis.mechanism_id
            or not set(self.assumption_ids).issubset(hypothesis.assumption_ids)
            or len(self.assumption_ids) != len(set(self.assumption_ids))
        ):
            raise ValueError("negative result must bind its hypothesis mechanism and assumptions")
        if evidence.content_hash != run.plan.evidence_binding.content_hash:
            raise ValueError("negative result evidence must match its run")
        if self.recorded_at < run.completed_at:
            raise ValueError("negative result cannot predate its run completion")
        return self


class ResearchArchive(_SealedScienceModel):
    """Immutable negative-result archive with deterministic exact-match surfacing."""

    archive_id: str = Field(min_length=1)
    programme_id: str = Field(min_length=1)
    negative_results: tuple[NegativeResult, ...] = ()
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def revalidates_unique_same_programme_results(self) -> ResearchArchive:
        results = tuple(
            NegativeResult.model_validate(result.model_dump(mode="json"))
            for result in self.negative_results
        )
        if any(result.content_hash is None for result in results):
            raise ValueError("research archive requires sealed negative results")
        ids = [result.negative_result_id for result in results]
        if len(ids) != len(set(ids)):
            raise ValueError("research archive negative result IDs must be unique")
        if any(result.run.programme_id != self.programme_id for result in results):
            raise ValueError("research archive result programme IDs must match")
        return self

    def surfaced_negative_results(self, hypothesis: Hypothesis) -> tuple[NegativeResult, ...]:
        archive = type(self).model_validate(self.model_dump(mode="json"))
        validated = Hypothesis.model_validate(hypothesis.model_dump(mode="json"))
        if archive.content_hash is None or validated.content_hash is None:
            raise ValueError("negative-result surfacing requires sealed archive and hypothesis")
        matching = [
            result
            for result in archive.negative_results
            if result.mechanism_id == validated.mechanism_id
            or set(result.assumption_ids).intersection(validated.assumption_ids)
        ]
        return tuple(
            sorted(
                matching,
                key=lambda result: (
                    -(result.mechanism_id == validated.mechanism_id),
                    -len(set(result.assumption_ids).intersection(validated.assumption_ids)),
                    result.negative_result_id,
                ),
            )
        )

    def validate_novelty_report(self, report: NoveltyReport) -> None:
        archive = type(self).model_validate(self.model_dump(mode="json"))
        validated = NoveltyReport.model_validate(report.model_dump(mode="json"))
        surfaced = archive.surfaced_negative_results(validated.hypothesis)
        if any(result.recorded_at > validated.assessed_at for result in surfaced):
            raise ValueError("novelty report can include only prior negative results")
        expected = tuple(result.negative_result_id for result in surfaced)
        if validated.surfaced_negative_result_ids != expected:
            raise ValueError("novelty report must include exactly the surfaced negative results")


class ResearchPostmortem(_SealedScienceModel):
    """Evidence-bound review that preserves negative and inconclusive outcomes."""

    postmortem_id: str = Field(min_length=1)
    run: ExperimentRun
    outcome: Literal["positive", "negative", "inconclusive"]
    negative_result: NegativeResult | None = None
    reviewer_id: str = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    recorded_at: AwareDatetime
    evidence_binding: ResearchEvidenceBinding
    authority: Literal["candidate_only"] = "candidate_only"
    release_disposition: Literal["engineering_only"] = "engineering_only"

    @model_validator(mode="after")
    def binds_outcome_run_evidence_and_lifecycle(self) -> ResearchPostmortem:
        run = ExperimentRun.model_validate(self.run.model_dump(mode="json"))
        evidence = ResearchEvidenceBinding.model_validate(
            self.evidence_binding.model_dump(mode="json")
        )
        negative = (
            NegativeResult.model_validate(self.negative_result.model_dump(mode="json"))
            if self.negative_result is not None
            else None
        )
        if run.content_hash is None or evidence.content_hash is None:
            raise ValueError("research postmortem requires sealed run and evidence")
        if evidence.content_hash != run.plan.evidence_binding.content_hash:
            raise ValueError("research postmortem evidence must match its run")
        if self.outcome in {"negative", "inconclusive"} and (
            negative is None or negative.run.content_hash != run.content_hash
        ):
            raise ValueError("negative or inconclusive postmortem requires its negative result")
        if negative is not None and (
            (self.outcome == "negative" and negative.disposition != "rejected")
            or (self.outcome == "inconclusive" and negative.disposition != "inconclusive")
        ):
            raise ValueError("postmortem outcome must match its negative-result disposition")
        if self.outcome == "positive" and negative is not None:
            raise ValueError("positive postmortem cannot bind a negative result")
        if self.outcome == "positive" and run.status != "passed":
            raise ValueError("positive postmortem requires a passed run")
        if self.recorded_at < run.completed_at or (
            negative is not None and self.recorded_at < negative.recorded_at
        ):
            raise ValueError("research postmortem cannot predate its supporting records")
        if len(self.limitations) != len(set(self.limitations)) or any(
            not limitation for limitation in self.limitations
        ):
            raise ValueError("research postmortem limitations must be unique and non-empty")
        return self


class ResearchContribution(_SealedScienceModel):
    mechanism_path: str = Field(min_length=1)
    amount: float = Field(allow_inf_nan=False)


class ResearchContributionReport(_SealedScienceModel):
    report_id: str = Field(min_length=1)
    contributions: tuple[ResearchContribution, ...] = Field(min_length=1)
    total: float = Field(allow_inf_nan=False)
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def reconciles_unique_mechanism_paths(self) -> ResearchContributionReport:
        contributions = tuple(
            ResearchContribution.model_validate(item.model_dump(mode="json"))
            for item in self.contributions
        )
        if any(item.content_hash is None for item in contributions):
            raise ValueError("contribution report requires sealed contributions")
        paths = [item.mechanism_path for item in contributions]
        if len(paths) != len(set(paths)):
            raise ValueError("contribution mechanism paths must be unique")
        if self.total != sum(item.amount for item in contributions):
            raise ValueError("research contributions must reconcile exactly")
        return self


class ResearchPortfolioCandidate(_SealedScienceModel):
    """Finite read-only research candidate; scoring grants no spending authority."""

    candidate_id: str = Field(min_length=1)
    programme: ResearchProgramme
    expected_validity: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    decision_value: float = Field(ge=0.0, allow_inf_nan=False)
    novelty: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    strategic_fit: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    compute_cost: float = Field(ge=0.0, allow_inf_nan=False)
    data_cost: float = Field(ge=0.0, allow_inf_nan=False)
    review_cost: float = Field(ge=0.0, allow_inf_nan=False)
    redundancy_penalty: float = Field(ge=0.0, allow_inf_nan=False)
    total_cost: float = Field(gt=0.0, allow_inf_nan=False)
    expected_voi: float = Field(allow_inf_nan=False)
    priority_score: float = Field(ge=0.0, allow_inf_nan=False)
    deadline: AwareDatetime
    redundant: bool = False
    robust: bool = True
    uncertainty_decision_changing: bool = True
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def recomputes_cost_voi_and_priority(self) -> ResearchPortfolioCandidate:
        programme = ResearchProgramme.model_validate(self.programme.model_dump(mode="json"))
        if programme.content_hash is None:
            raise ValueError("research portfolio candidate requires a sealed programme")
        if programme.status == "stopped":
            raise ValueError("research portfolio candidate cannot use a stopped programme")
        expected_cost = (
            self.compute_cost + self.data_cost + self.review_cost + self.redundancy_penalty
        )
        benefit = self.expected_validity * self.decision_value * self.novelty * self.strategic_fit
        expected_voi = benefit - expected_cost
        priority_score = benefit / expected_cost
        if self.total_cost != expected_cost:
            raise ValueError("research portfolio candidate total cost must reconcile")
        if self.expected_voi != expected_voi:
            raise ValueError("research portfolio candidate expected VOI must be recomputed")
        if self.priority_score != priority_score:
            raise ValueError("research portfolio candidate priority score must be recomputed")
        return self


ResearchPortfolioStopReason = Literal[
    "non_positive_voi",
    "redundancy",
    "budget",
    "deadline",
    "robustness",
    "non_decision_changing_uncertainty",
]


def _portfolio_selection(
    *,
    as_of: AwareDatetime,
    budget: ResearchBudget,
    candidates: tuple[ResearchPortfolioCandidate, ...],
) -> tuple[
    tuple[str, ...],
    ResearchPortfolioStopReason | None,
    tuple[float, float, float, float, float],
]:
    positive = tuple(candidate for candidate in candidates if candidate.expected_voi > 0.0)
    if not positive:
        return (), "non_positive_voi", (0.0, 0.0, 0.0, 0.0, 0.0)
    nonredundant = tuple(candidate for candidate in positive if not candidate.redundant)
    if not nonredundant:
        return (), "redundancy", (0.0, 0.0, 0.0, 0.0, 0.0)
    timely = tuple(candidate for candidate in nonredundant if candidate.deadline > as_of)
    if not timely:
        return (), "deadline", (0.0, 0.0, 0.0, 0.0, 0.0)
    robust = tuple(candidate for candidate in timely if candidate.robust)
    if not robust:
        return (), "robustness", (0.0, 0.0, 0.0, 0.0, 0.0)
    decision_changing = tuple(
        candidate for candidate in robust if candidate.uncertainty_decision_changing
    )
    if not decision_changing:
        return (), "non_decision_changing_uncertainty", (0.0, 0.0, 0.0, 0.0, 0.0)

    ordered = sorted(
        decision_changing,
        key=lambda candidate: (-candidate.priority_score, candidate.programme.programme_id),
    )
    selected: list[str] = []
    compute = data = review = redundancy = total = 0.0
    for candidate in ordered:
        next_compute = compute + candidate.compute_cost
        next_data = data + candidate.data_cost
        next_review = review + candidate.review_cost
        next_redundancy = redundancy + candidate.redundancy_penalty
        next_total = total + candidate.total_cost
        if (
            next_compute <= budget.compute_limit
            and next_data <= budget.data_limit
            and next_review <= budget.review_limit
            and next_total <= budget.total_limit
        ):
            selected.append(candidate.candidate_id)
            compute, data, review, redundancy, total = (
                next_compute,
                next_data,
                next_review,
                next_redundancy,
                next_total,
            )
    if not selected:
        return (), "budget", (0.0, 0.0, 0.0, 0.0, 0.0)
    return tuple(selected), None, (compute, data, review, redundancy, total)


class ResearchPortfolio(_SealedScienceModel):
    """Deterministic read-only research ranking; it cannot initiate or fund work."""

    portfolio_id: str = Field(min_length=1)
    as_of: AwareDatetime
    budget: ResearchBudget
    candidates: tuple[ResearchPortfolioCandidate, ...] = Field(min_length=1)
    selected_candidate_ids: tuple[str, ...] = ()
    stop_reason: ResearchPortfolioStopReason | None = None
    selected_compute_cost: float = Field(ge=0.0, allow_inf_nan=False)
    selected_data_cost: float = Field(ge=0.0, allow_inf_nan=False)
    selected_review_cost: float = Field(ge=0.0, allow_inf_nan=False)
    selected_redundancy_penalty: float = Field(ge=0.0, allow_inf_nan=False)
    total_selected_cost: float = Field(ge=0.0, allow_inf_nan=False)
    authority: Literal["candidate_only"] = "candidate_only"
    release_disposition: Literal["engineering_only"] = "engineering_only"

    @model_validator(mode="after")
    def recomputes_selection_and_costs(self) -> ResearchPortfolio:
        budget = ResearchBudget.model_validate(self.budget.model_dump(mode="json"))
        candidates = tuple(
            ResearchPortfolioCandidate.model_validate(candidate.model_dump(mode="json"))
            for candidate in self.candidates
        )
        if budget.content_hash is None or any(
            candidate.content_hash is None for candidate in candidates
        ):
            raise ValueError("research portfolio requires sealed budget and candidates")
        candidate_ids = [candidate.candidate_id for candidate in candidates]
        programme_ids = [candidate.programme.programme_id for candidate in candidates]
        if len(candidate_ids) != len(set(candidate_ids)) or len(programme_ids) != len(
            set(programme_ids)
        ):
            raise ValueError("research portfolio candidate and programme IDs must be unique")
        if any(
            candidate.programme.as_of > self.as_of
            or candidate.programme.evidence_binding.as_of > self.as_of
            for candidate in candidates
        ):
            raise ValueError("research portfolio candidate evidence is after the portfolio cutoff")
        expected_ids, expected_reason, expected_costs = _portfolio_selection(
            as_of=self.as_of,
            budget=budget,
            candidates=candidates,
        )
        actual_costs = (
            self.selected_compute_cost,
            self.selected_data_cost,
            self.selected_review_cost,
            self.selected_redundancy_penalty,
            self.total_selected_cost,
        )
        if self.selected_candidate_ids != expected_ids or self.stop_reason != expected_reason:
            raise ValueError("research portfolio selection or stop reason mismatch")
        if actual_costs != expected_costs:
            raise ValueError("research portfolio selected costs must reconcile")
        return self


def rank_research_portfolio(
    *,
    portfolio_id: str,
    as_of: AwareDatetime,
    budget: ResearchBudget,
    candidates: tuple[ResearchPortfolioCandidate, ...],
) -> ResearchPortfolio:
    """Return a sealed deterministic selection or one explicit stop reason."""

    validated_budget = ResearchBudget.model_validate(budget.model_dump(mode="json"))
    validated_candidates = tuple(
        ResearchPortfolioCandidate.model_validate(candidate.model_dump(mode="json"))
        for candidate in candidates
    )
    selected, reason, costs = _portfolio_selection(
        as_of=as_of,
        budget=validated_budget,
        candidates=validated_candidates,
    )
    return ResearchPortfolio(
        portfolio_id=portfolio_id,
        as_of=as_of,
        budget=validated_budget,
        candidates=validated_candidates,
        selected_candidate_ids=selected,
        stop_reason=reason,
        selected_compute_cost=costs[0],
        selected_data_cost=costs[1],
        selected_review_cost=costs[2],
        selected_redundancy_penalty=costs[3],
        total_selected_cost=costs[4],
    ).sealed()
