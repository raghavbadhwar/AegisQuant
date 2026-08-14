"""Deterministic local immutable-object recovery drills for a fresh target directory."""

from __future__ import annotations

from datetime import datetime

from aegisquant.contracts.artifact import BlobRef
from aegisquant.contracts.common import require_utc
from aegisquant.contracts.recovery import (
    ObjectStoreRecoveryCommand,
    ObjectStoreRecoveryReceipt,
    object_store_content_manifest_digest,
    object_store_recovery_receipt_digest,
)
from aegisquant.object_store.local_immutable import LocalImmutableObjectStore


class ObjectStoreRecoveryError(ValueError):
    pass


def run_local_object_store_recovery_drill(
    command: ObjectStoreRecoveryCommand,
    *,
    source: LocalImmutableObjectStore,
    target: LocalImmutableObjectStore,
    completed_at: datetime,
) -> ObjectStoreRecoveryReceipt:
    """Restore exact source objects into an empty target; no deletion or network is involved."""

    completed_at = require_utc(completed_at)
    if completed_at < command.started_at:
        raise ObjectStoreRecoveryError("recovery drill completed before it started")
    if command.source_content_manifest_digest != object_store_content_manifest_digest(
        command.source_references
    ):
        raise ObjectStoreRecoveryError("recovery command source manifest is mismatched")
    if source.root == target.root:
        raise ObjectStoreRecoveryError("recovery source and target must be different")
    if any(target.root.iterdir()):
        raise ObjectStoreRecoveryError("recovery target must be empty")
    total_bytes = sum(reference.size_bytes for reference in command.source_references)
    if total_bytes > command.max_total_bytes:
        raise ObjectStoreRecoveryError("recovery command exceeds its declared byte limit")
    recovered: list[BlobRef] = []
    for reference in command.source_references:
        data = source.get(reference, authenticated_tenant_id=command.tenant_id)
        restored = target.put_if_absent(
            tenant_id=command.tenant_id,
            data=data,
            media_type=reference.media_type,
            retention_class=reference.retention_class,
        )
        if target.get(restored, authenticated_tenant_id=command.tenant_id) != data:
            raise ObjectStoreRecoveryError("recovered object failed read-back verification")
        recovered.append(restored)
    recovered_digest = object_store_content_manifest_digest(recovered)
    if recovered_digest != command.source_content_manifest_digest:
        raise ObjectStoreRecoveryError("recovery content manifest changed during restore")
    return ObjectStoreRecoveryReceipt(
        tenant_id=command.tenant_id,
        drill_id=command.drill_id,
        source_content_manifest_digest=command.source_content_manifest_digest,
        recovered_content_manifest_digest=recovered_digest,
        recovered_references=tuple(recovered),
        object_count=len(recovered),
        total_bytes=total_bytes,
        recovery_digest=object_store_recovery_receipt_digest(
            tenant_id=command.tenant_id,
            drill_id=command.drill_id,
            source_content_manifest_digest=command.source_content_manifest_digest,
            recovered_content_manifest_digest=recovered_digest,
            recovered_references=tuple(recovered),
            object_count=len(recovered),
            total_bytes=total_bytes,
            completed_at=completed_at,
        ),
        completed_at=completed_at,
    )
