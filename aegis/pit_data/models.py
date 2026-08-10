"""Canonical contracts for sealed point-in-time artifacts and snapshots."""

from __future__ import annotations

from typing import Any

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel


class PITArtifact(CandidateContractModel):
    """A raw historical source artifact whose availability is explicitly causal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    security_id: str | None = None
    artifact_type: str = Field(min_length=1)
    form: str | None = None
    accession: str | None = None
    observed_at: AwareDatetime | None = None
    period_start: AwareDatetime | None = None
    period_end: AwareDatetime | None = None
    filed_at: AwareDatetime | None = None
    accepted_at: AwareDatetime | None = None
    available_at: AwareDatetime
    ingested_at: AwareDatetime
    revision: str | None = None
    supersedes_artifact_id: str | None = None
    raw_path: str = Field(min_length=1)
    parsed_path: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def enforce_temporal_causality(self) -> PITArtifact:
        if self.filed_at is not None and self.available_at < self.filed_at:
            raise ValueError("artifact availability cannot precede filing")
        if self.accepted_at is not None and self.available_at < self.accepted_at:
            raise ValueError("artifact availability cannot precede acceptance")
        return self


class SecurityMasterRecord(CandidateContractModel):
    """Historical identifier mapping; do not assume today's ticker mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_security_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    cik: str | None = Field(default=None, pattern=r"^\d{10}$")
    cusip: str | None = None
    issuer: str = Field(min_length=1)
    exchange: str | None = None
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None = None
    source: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_available_at: AwareDatetime
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_raw_uri: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_history_interval(self) -> SecurityMasterRecord:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("security mapping validity interval is inverted")
        return self


class PITSnapshotManifest(CandidateContractModel):
    """Hash-bound offline information world for a single simulation timestamp."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "aegis-pit-snapshot-v1"
    simulation_at: AwareDatetime
    built_at: AwareDatetime
    artifact_count: int = Field(ge=0)
    universe: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    artifact_hashes: tuple[str, ...]
    security_record_ids: tuple[str, ...] = ()
    security_record_hashes: tuple[str, ...] = ()
    dataset_version: str = Field(min_length=1)
    parser_versions: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    manifest_hash: str | None = None

    @model_validator(mode="after")
    def valid_manifest(self) -> PITSnapshotManifest:
        if self.artifact_count != len(self.artifact_ids):
            raise ValueError("snapshot artifact count mismatch")
        if len(self.artifact_ids) != len(set(self.artifact_ids)):
            raise ValueError("snapshot artifact IDs must be unique")
        if len(self.artifact_hashes) != self.artifact_count:
            raise ValueError("snapshot artifact hash count mismatch")
        if any(item != item.lower() or len(item) != 64 for item in self.artifact_hashes):
            raise ValueError("snapshot artifact hashes must be sha256 values")
        if len(self.security_record_ids) != len(set(self.security_record_ids)):
            raise ValueError("snapshot security record IDs must be unique")
        if len(self.security_record_ids) != len(self.security_record_hashes):
            raise ValueError("snapshot security record hash count mismatch")
        if any(item != item.lower() or len(item) != 64 for item in self.security_record_hashes):
            raise ValueError("snapshot security record hashes must be sha256 values")
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"built_at", "manifest_hash"})
        )
        if self.manifest_hash is not None and self.manifest_hash != expected:
            raise ValueError("snapshot manifest hash mismatch")
        return self

    def sealed(self) -> PITSnapshotManifest:
        return self.model_copy(
            update={
                "manifest_hash": canonical_sha256(
                    self.model_dump(mode="json", exclude={"built_at", "manifest_hash"})
                )
            }
        )
