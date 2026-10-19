"""Immutable-object recovery-drill contracts for the supported local profile."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.artifact import BlobRef
from aegisquant.contracts.common import Identifier, Sha256Digest, StrictModel, require_utc
from aegisquant.security.digests import digest_canonical


def _parse_utc(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("recovery timestamps must be UTC datetimes")
    return require_utc(value)


def object_store_content_manifest_digest(references: Iterable[BlobRef]) -> str:
    return digest_canonical(
        tuple(
            {
                "tenant_id": reference.tenant_id,
                "content_digest": reference.content_digest,
                "size_bytes": reference.size_bytes,
                "media_type": reference.media_type,
                "retention_class": reference.retention_class,
            }
            for reference in references
        )
    )


def object_store_recovery_receipt_digest(
    *,
    tenant_id: str,
    drill_id: str,
    source_content_manifest_digest: str,
    recovered_content_manifest_digest: str,
    recovered_references: tuple[BlobRef, ...],
    object_count: int,
    total_bytes: int,
    completed_at: datetime,
) -> str:
    return digest_canonical(
        {
            "tenant_id": tenant_id,
            "drill_id": drill_id,
            "source_content_manifest_digest": source_content_manifest_digest,
            "recovered_content_manifest_digest": recovered_content_manifest_digest,
            "recovered_references": recovered_references,
            "object_count": object_count,
            "total_bytes": total_bytes,
            "completed_at": completed_at,
        }
    )


class ObjectStoreRecoveryCommand(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    drill_id: Identifier
    source_content_manifest_digest: Sha256Digest
    source_references: tuple[BlobRef, ...] = Field(min_length=1)
    max_total_bytes: int = Field(ge=1)
    initiated_by: Identifier
    started_at: datetime

    @field_validator("source_references", mode="before")
    @classmethod
    def reference_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("started_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)

    @model_validator(mode="after")
    def references_share_tenant(self) -> ObjectStoreRecoveryCommand:
        if any(reference.tenant_id != self.tenant_id for reference in self.source_references):
            raise ValueError("recovery references must share the command tenant")
        digests = [reference.content_digest for reference in self.source_references]
        if len(digests) != len(set(digests)):
            raise ValueError("recovery references must have unique content digests")
        return self


class ObjectStoreRecoveryReceipt(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    drill_id: Identifier
    source_content_manifest_digest: Sha256Digest
    recovered_content_manifest_digest: Sha256Digest
    recovered_references: tuple[BlobRef, ...]
    object_count: int = Field(ge=1)
    total_bytes: int = Field(ge=0)
    recovery_digest: Sha256Digest
    completed_at: datetime

    @field_validator("recovered_references", mode="before")
    @classmethod
    def reference_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("completed_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)

    @model_validator(mode="after")
    def recovered_scope(self) -> ObjectStoreRecoveryReceipt:
        if (
            self.source_content_manifest_digest != self.recovered_content_manifest_digest
            or self.object_count != len(self.recovered_references)
            or self.total_bytes
            != sum(reference.size_bytes for reference in self.recovered_references)
            or any(reference.tenant_id != self.tenant_id for reference in self.recovered_references)
            or self.recovered_content_manifest_digest
            != object_store_content_manifest_digest(self.recovered_references)
            or self.recovery_digest
            != object_store_recovery_receipt_digest(
                tenant_id=self.tenant_id,
                drill_id=self.drill_id,
                source_content_manifest_digest=self.source_content_manifest_digest,
                recovered_content_manifest_digest=self.recovered_content_manifest_digest,
                recovered_references=self.recovered_references,
                object_count=self.object_count,
                total_bytes=self.total_bytes,
                completed_at=self.completed_at,
            )
        ):
            raise ValueError("recovery receipt is internally inconsistent")
        return self
