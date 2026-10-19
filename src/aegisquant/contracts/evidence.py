"""Point-in-time evidence, source rights, and numeric-claim contracts."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import (
    FixedDecimal,
    Identifier,
    Sha256Digest,
    StrictModel,
    require_utc,
)


class RightsDecision(StrEnum):
    ALLOW = "ALLOW"
    QUARANTINE = "QUARANTINE"
    DENY = "DENY"


class RightsManifest(StrictModel):
    schema_version: Literal[1] = 1
    rights_manifest_id: Identifier
    terms_version: Identifier
    decision: RightsDecision
    allowed_purposes: tuple[Identifier, ...]
    allowed_tenant_ids: tuple[Identifier, ...]
    may_store: bool
    may_embed: bool
    may_send_to_external_model: bool
    may_create_derivatives: bool
    may_display: bool
    may_export: bool
    retention_days: int | None = Field(default=None, ge=1)
    attribution_required: bool
    territory_codes: tuple[str, ...] = ()
    decided_at: datetime
    expires_at: datetime | None = None

    @field_validator("decided_at", "expires_at")
    @classmethod
    def times_are_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def unknown_rights_cannot_allow_use(self) -> "RightsManifest":
        if self.decision != RightsDecision.ALLOW and any(
            (
                self.may_store,
                self.may_embed,
                self.may_send_to_external_model,
                self.may_create_derivatives,
                self.may_display,
                self.may_export,
            )
        ):
            raise ValueError("non-ALLOW rights decision cannot grant usage")
        return self


class EvidenceRecord(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    evidence_id: UUID
    source_type: Identifier
    source_url: str | None = Field(default=None, max_length=2048)
    entity_ids: tuple[Identifier, ...]
    document_type: Identifier
    event_time: datetime | None = None
    published_at: datetime | None = None
    first_observed_at: datetime
    available_at: datetime
    ingested_at: datetime
    revised_at: datetime | None = None
    vendor_ingested_at: datetime | None = None
    raw_object_uri: str = Field(min_length=1, max_length=2048)
    raw_content_digest: Sha256Digest
    capture_metadata_digest: Sha256Digest
    extractor_version: Identifier
    parser_version: Identifier
    rights_manifest_id: Identifier
    source_quality: FixedDecimal
    extraction_confidence: FixedDecimal
    historical_safe: bool
    untrusted_content: Literal[True] = True
    prompt_injection_flags: tuple[Identifier, ...] = ()
    revision_id: Identifier | None = None

    @field_validator("entity_ids", "prompt_injection_flags", mode="before")
    @classmethod
    def json_arrays_are_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator(
        "event_time",
        "published_at",
        "first_observed_at",
        "available_at",
        "ingested_at",
        "revised_at",
        "vendor_ingested_at",
        mode="before",
    )
    @classmethod
    def times_are_utc(cls, value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise ValueError("evidence times must be UTC datetimes")
        return require_utc(value)

    @field_validator("source_quality", "extraction_confidence")
    @classmethod
    def score_is_unit_interval(cls, value: Decimal) -> Decimal:
        if not Decimal(0) <= value <= Decimal(1):
            raise ValueError("quality/confidence must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def chronology_is_consistent(self) -> "EvidenceRecord":
        if self.available_at < self.first_observed_at:
            raise ValueError("available_at cannot precede trusted first_observed_at")
        if self.ingested_at < self.first_observed_at:
            raise ValueError("ingested_at cannot precede first_observed_at")
        if self.revised_at is not None and self.revised_at < self.available_at:
            raise ValueError("revised_at cannot precede available_at")
        return self

    def eligible_as_of(self, analysis_time: datetime) -> bool:
        analysis_time = require_utc(analysis_time)
        return self.historical_safe and self.available_at <= analysis_time


class NumericClaim(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    claim_id: UUID
    name: Identifier
    value: FixedDecimal
    unit: Identifier
    evidence_id: UUID
    source_coordinate: str = Field(min_length=1, max_length=512)
    calculation_id: Identifier | None = None
