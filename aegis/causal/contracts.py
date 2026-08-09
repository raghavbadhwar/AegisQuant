"""Strict causal-thesis contracts for v4 candidate research only.

These contracts never confer execution, promotion, or factual authority.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256


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


class IdentificationRecord(BaseModel):
    """Evidence-bound method and failed/refutation record for C2+ support."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identification_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    adjustment_set: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    refutation_ids: tuple[str, ...] = Field(min_length=1)
    validated_at: AwareDatetime
    validator_id: str = Field(min_length=1)


class CausalEdge(BaseModel):
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
        if (
            self.kind == CausalEdgeKind.STRUCTURAL_MECHANISM
            and self.support_level != CausalSupportLevel.C3_STRUCTURAL
        ):
            raise ValueError("structural mechanism requires C3 support")
        if (
            self.support_level
            in {CausalSupportLevel.C2_IDENTIFIED, CausalSupportLevel.C3_STRUCTURAL}
            and self.identification is None
        ):
            raise ValueError("C2/C3 causal support requires an identification record")
        if self.support_level == CausalSupportLevel.C3_STRUCTURAL and not self.mechanism_model_id:
            raise ValueError("C3 causal support requires a mechanism model")
        if self.status in {EdgeStatus.REFUTED, EdgeStatus.SUPERSEDED} and self.kind in {
            CausalEdgeKind.IDENTIFIED_CAUSE,
            CausalEdgeKind.STRUCTURAL_MECHANISM,
        }:
            raise ValueError("refuted/superseded edge cannot retain identified authority")
        return self


class CausalGraphSnapshot(BaseModel):
    """Immutable, versioned causal graph separate from the evidence claim DAG."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    as_of: AwareDatetime
    domain_pack: str = Field(min_length=1)
    edges: tuple[CausalEdge, ...]
    evidence_ids: tuple[str, ...]
    parent_snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_snapshot(self) -> CausalGraphSnapshot:
        ids = [edge.edge_id for edge in self.edges]
        if len(ids) != len(set(ids)):
            raise ValueError("causal graph edge IDs must be unique")
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
        )
