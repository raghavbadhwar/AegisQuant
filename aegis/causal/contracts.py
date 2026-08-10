"""Strict causal-thesis contracts for v4 candidate research only.

These contracts never confer execution, promotion, or factual authority.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel


class CausalEdgeKind(StrEnum):
    ASSOCIATED = "associated"
    PRECEDES = "precedes"
    PREDICTS = "predicts"
    HYPOTHESIZED_CAUSE = "hypothesized_cause"
    IDENTIFIED_CAUSE = "identified_cause"
    STRUCTURAL_MECHANISM = "structural_mechanism"
    MEDIATES = "mediates"
    MODERATES = "moderates"
    CONFOUNDS = "confounds"


class EdgeStatus(StrEnum):
    DRAFT = "draft"
    SUPPORTED = "supported"
    CHALLENGED = "challenged"
    REFUTED = "refuted"
    SUPERSEDED = "superseded"
    VALIDATED_FOR_DOMAIN = "validated_for_domain"


class CausalSupportLevel(StrEnum):
    C0_NARRATIVE = "c0_narrative"
    C1_TEMPORAL_PREDICTIVE = "c1_temporal_predictive"
    C2_IDENTIFIED = "c2_identified"
    C3_STRUCTURAL = "c3_structural"


class RefutationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class IdentificationStatus(StrEnum):
    IDENTIFIED = "IDENTIFIED"
    NOT_IDENTIFIED = "NOT_IDENTIFIED"
    REFUTATION_FAILED = "REFUTATION_FAILED"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"


class RefutationRecord(CandidateContractModel):
    """One evidence-bound falsification result with no promotion authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    refutation_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    status: RefutationStatus
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    evaluated_at: AwareDatetime
    evaluator_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> RefutationRecord:
        groups = (self.assumption_ids, self.evidence_ids)
        if any(
            any(not item for item in group) or len(group) != len(set(group)) for group in groups
        ):
            raise ValueError("refutation identifiers must be unique and nonempty")
        return self


class IdentificationRecord(CandidateContractModel):
    """Evidence-bound method and failed/refutation record for C2+ support."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identification_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    adjustment_set: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    refutations: tuple[RefutationRecord, ...] = Field(min_length=1)
    validated_at: AwareDatetime
    validator_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def requires_passing_refutations(self) -> IdentificationRecord:
        refutation_ids = [refutation.refutation_id for refutation in self.refutations]
        if len(refutation_ids) != len(set(refutation_ids)):
            raise ValueError("identification refutation IDs must be unique")
        if any(refutation.status != RefutationStatus.PASSED for refutation in self.refutations):
            raise ValueError("identified status is unavailable after a failed refutation")
        if any(
            not set(refutation.evidence_ids).issubset(self.evidence_ids)
            for refutation in self.refutations
        ):
            raise ValueError("identification refutation evidence must be declared")
        if any(
            not set(refutation.assumption_ids).issubset(self.assumption_ids)
            for refutation in self.refutations
        ):
            raise ValueError("identification refutation assumptions must be declared")
        return self


class CausalEdge(CandidateContractModel):
    """One versioned causal candidate whose semantic authority is fail-closed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: str = Field(min_length=1)
    source_variable_id: str = Field(min_length=1)
    target_variable_id: str = Field(min_length=1)
    kind: CausalEdgeKind
    status: EdgeStatus
    support_level: CausalSupportLevel
    mechanism_description: str = Field(min_length=1)
    sign: int = Field(ge=-1, le=1)
    evidence_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    confounder_ids: tuple[str, ...] = ()
    identification: IdentificationRecord | None = None
    mechanism_model_id: str | None = None
    competing_mechanism_group_id: str | None = Field(default=None, min_length=1)
    domain_pack: str = Field(min_length=1)
    known_from: AwareDatetime
    valid_from: AwareDatetime | None = None
    valid_to: AwareDatetime | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def enforce_causal_authority(self) -> CausalEdge:
        if self.source_variable_id == self.target_variable_id:
            raise ValueError("causal edge cannot self-reference")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("causal edge validity interval is inverted")
        if self.kind == CausalEdgeKind.IDENTIFIED_CAUSE and self.support_level not in {
            CausalSupportLevel.C2_IDENTIFIED,
            CausalSupportLevel.C3_STRUCTURAL,
        }:
            raise ValueError("identified causal edge requires C2 or C3 support")
        if self.kind == CausalEdgeKind.IDENTIFIED_CAUSE and self.status not in {
            EdgeStatus.SUPPORTED,
            EdgeStatus.VALIDATED_FOR_DOMAIN,
        }:
            raise ValueError("identified causal edge requires a supported status")
        if (
            self.kind == CausalEdgeKind.STRUCTURAL_MECHANISM
            and self.support_level != CausalSupportLevel.C3_STRUCTURAL
        ):
            raise ValueError("structural mechanism requires C3 support")
        if (
            self.kind == CausalEdgeKind.STRUCTURAL_MECHANISM
            and self.status != EdgeStatus.VALIDATED_FOR_DOMAIN
        ):
            raise ValueError("structural mechanism must be validated for its domain")
        if (
            self.support_level
            in {CausalSupportLevel.C2_IDENTIFIED, CausalSupportLevel.C3_STRUCTURAL}
            and self.identification is None
        ):
            raise ValueError("C2/C3 causal support requires an identification record")
        if self.support_level == CausalSupportLevel.C3_STRUCTURAL and not self.mechanism_model_id:
            raise ValueError("C3 causal support requires a mechanism model")
        if self.identification is not None and (
            set(self.identification.evidence_ids) != set(self.evidence_ids)
            or set(self.identification.assumption_ids) != set(self.assumption_ids)
        ):
            raise ValueError("identification evidence and assumptions must bind the causal edge")
        if self.identification is not None and not set(self.confounder_ids).issubset(
            self.identification.adjustment_set
        ):
            raise ValueError("identification adjustment set omits a declared confounder")
        if self.status in {EdgeStatus.REFUTED, EdgeStatus.SUPERSEDED} and self.kind in {
            CausalEdgeKind.IDENTIFIED_CAUSE,
            CausalEdgeKind.STRUCTURAL_MECHANISM,
        }:
            raise ValueError("refuted/superseded edge cannot retain identified authority")
        return self


class CausalGraphSnapshot(CandidateContractModel):
    """Immutable, versioned causal graph separate from the evidence claim DAG."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    graph_version: int = Field(default=1, ge=1)
    as_of: AwareDatetime
    domain_pack: str = Field(min_length=1)
    edges: tuple[CausalEdge, ...]
    evidence_ids: tuple[str, ...]
    parent_snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_snapshot(self) -> CausalGraphSnapshot:
        if (self.graph_version == 1) != (self.parent_snapshot_hash is None):
            raise ValueError("causal graph parent hash must match its graph version")
        ids = [edge.edge_id for edge in self.edges]
        if len(ids) != len(set(ids)):
            raise ValueError("causal graph edge IDs must be unique")
        competing_groups: dict[str, list[CausalEdge]] = {}
        for edge in self.edges:
            if edge.competing_mechanism_group_id is not None:
                competing_groups.setdefault(edge.competing_mechanism_group_id, []).append(edge)
        for edges in competing_groups.values():
            if len(edges) < 2:
                raise ValueError("competing mechanism group requires at least two edges")
            if len({edge.target_variable_id for edge in edges}) != 1:
                raise ValueError("competing mechanism group must share one target")
        if any(edge.domain_pack != self.domain_pack for edge in self.edges):
            raise ValueError("causal graph edges must share snapshot domain pack")
        allowed = set(self.evidence_ids)
        if any(not set(edge.evidence_ids).issubset(allowed) for edge in self.edges):
            raise ValueError("causal edge cites evidence outside graph snapshot")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("causal graph content hash mismatch")
        return self

    def sealed(self) -> CausalGraphSnapshot:
        return self.model_copy(
            update={
                "content_hash": canonical_sha256(
                    self.model_dump(mode="json", exclude={"content_hash"})
                )
            }
        )

    def eligible_edges(self) -> tuple[CausalEdge, ...]:
        """Return candidates usable in a model; never includes refuted or future edges."""
        return tuple(
            edge
            for edge in self.edges
            if edge.status not in {EdgeStatus.REFUTED, EdgeStatus.SUPERSEDED}
            and edge.known_from <= self.as_of
            and (edge.valid_from is None or edge.valid_from <= self.as_of)
            and (edge.valid_to is None or self.as_of <= edge.valid_to)
            and (
                edge.identification is None
                or (
                    edge.identification.validated_at <= self.as_of
                    and all(
                        refutation.evaluated_at <= self.as_of
                        for refutation in edge.identification.refutations
                    )
                )
            )
        )


class IdentificationRequest(CandidateContractModel):
    """Candidate request to test one edge; never an instruction to promote it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    causal_graph: CausalGraphSnapshot
    edge_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    adjustment_set: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    refutation_methods: tuple[str, ...] = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> IdentificationRequest:
        groups = (
            self.adjustment_set,
            self.assumption_ids,
            self.evidence_ids,
            self.refutation_methods,
        )
        if any(
            any(not item for item in group) or len(group) != len(set(group)) for group in groups
        ):
            raise ValueError("identification request identifiers must be unique and nonempty")
        return self


class IdentificationOutcome(CandidateContractModel):
    """Typed identification result or explicit abstention with candidate-only authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    edge_id: str = Field(min_length=1)
    status: IdentificationStatus
    reason: str = Field(min_length=1)
    causal_graph_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    identification: IdentificationRecord | None = None
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def identified_status_requires_a_record(self) -> IdentificationOutcome:
        if (self.status == IdentificationStatus.IDENTIFIED) != (self.identification is not None):
            raise ValueError("only identified status may carry an identification record")
        if self.status == IdentificationStatus.IDENTIFIED and self.causal_graph_hash is None:
            raise ValueError("identified status must bind a sealed causal graph")
        return self
