"""Candidate-only domain-pack manifest contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel

_STABLE_ID = r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$"
_SHA256 = r"^[0-9a-f]{64}$"


class DomainPackStatus(StrEnum):
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    APPROVED = "approved"
    RETIRED = "retired"


class DomainPackManifest(CandidateContractModel):
    """Content-addressed, not authenticated, domain-bounded candidate manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain_pack_id: str = Field(pattern=_STABLE_ID)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    supported_entities: tuple[str, ...] = Field(min_length=1)
    supported_variables: tuple[str, ...] = Field(min_length=1)
    supported_interventions: tuple[str, ...] = Field(min_length=1)
    supported_horizons: tuple[str, ...] = Field(min_length=1)
    twin_ids: tuple[str, ...] = Field(min_length=1)
    mechanism_model_ids: tuple[str, ...] = Field(min_length=1)
    validation_report_id: str = Field(pattern=_STABLE_ID)
    coverage_limits: tuple[str, ...] = Field(min_length=1)
    known_failure_modes: tuple[str, ...] = Field(min_length=1)
    licence_metadata: tuple[str, ...] = Field(min_length=1)
    status: DomainPackStatus
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def validate_manifest(self) -> DomainPackManifest:
        declared_groups = (
            self.supported_entities,
            self.supported_variables,
            self.supported_interventions,
            self.supported_horizons,
            self.twin_ids,
            self.mechanism_model_ids,
        )
        if any(len(values) != len(set(values)) for values in declared_groups):
            raise ValueError("domain pack declarations must be unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("domain pack manifest content hash mismatch")
        return self

    def sealed(self) -> DomainPackManifest:
        """Return the deterministic, content-addressed candidate manifest."""
        return self.model_copy(
            update={
                "content_hash": canonical_sha256(
                    self.model_dump(mode="json", exclude={"content_hash"})
                )
            }
        )
