"""Evidence provenance contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from ._base import ContractModel, validate_sha256

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class EvidenceRecord(ContractModel):
    """A normalized, timestamped, content-addressed source record."""

    evidence_id: Annotated[str, Field(min_length=1)]
    source_id: Annotated[str, Field(min_length=1)]
    source_url: str | None = None
    content_hash: str
    raw_uri: Annotated[str, Field(min_length=1)]
    entity_ids: list[str] = Field(default_factory=list)
    document_type: Annotated[str, Field(min_length=1)]
    section: str | None = None
    page: int | None = Field(default=None, ge=1)
    coordinates: str | None = None
    event_time: AwareDatetime | None = None
    published_at: AwareDatetime | None = None
    available_at: AwareDatetime
    retrieved_at: AwareDatetime
    source_quality: UnitInterval
    extraction_confidence: UnitInterval
    historical_safe: bool
    injection_flags: list[str] = Field(default_factory=list)
    parser_version: Annotated[str, Field(min_length=1)]
    extractor_version: Annotated[str, Field(min_length=1)]
    source_manifest_version: Annotated[str, Field(min_length=1)] = "unversioned"
    normalized_content_hash: str | None = None

    @field_validator("content_hash")
    @classmethod
    def content_hash_is_sha256(cls, value: str) -> str:
        return validate_sha256(value)

    @model_validator(mode="after")
    def timestamps_are_causal(self) -> EvidenceRecord:
        if self.published_at is not None and self.published_at > self.available_at:
            raise ValueError("published_at must not be after available_at")
        if self.available_at > self.retrieved_at:
            raise ValueError("available_at must not be after retrieved_at")
        return self


class EvidenceBundle(ContractModel):
    """Evidence selected for one case at a point in time."""

    case_id: Annotated[str, Field(min_length=1)]
    as_of: AwareDatetime
    records: list[EvidenceRecord] = Field(default_factory=list)
    mode: Literal["replay", "historical", "live_research"] = "historical"

    @model_validator(mode="after")
    def ids_are_unique_and_point_in_time_safe(self) -> EvidenceBundle:
        ids = [record.evidence_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be unique")
        if any(record.available_at > self.as_of for record in self.records):
            raise ValueError("evidence available after bundle as_of is not point-in-time safe")
        if self.mode in {"replay", "historical"} and any(
            not record.historical_safe for record in self.records
        ):
            raise ValueError("evidence bundle contains a historically unsafe record")
        return self


class EvidenceAuditPolicy(ContractModel):
    minimum_extraction_confidence: UnitInterval = 0.7
    maximum_age_days: int | None = Field(default=None, ge=0)
    block_injection_flags: bool = True


class AuditFinding(ContractModel):
    code: Annotated[str, Field(min_length=1)]
    severity: Literal["warning", "blocker"]
    message: Annotated[str, Field(min_length=1)]
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)


class EvidenceAuditResult(ContractModel):
    case_id: Annotated[str, Field(min_length=1)]
    approved: bool
    approved_evidence_ids: list[str] = Field(default_factory=list)
    approved_claim_ids: list[str] = Field(default_factory=list)
    findings: list[AuditFinding] = Field(default_factory=list)
    audited_input_hash: str
