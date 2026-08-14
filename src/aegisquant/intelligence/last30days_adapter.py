"""Recorded-only Last30Days result binding.

This module deliberately never invokes the installed Last30Days process. A
separately verified egress proxy must first capture content through
``SourceGateway``; this adapter only binds that immutable capture to a case.
"""

from __future__ import annotations

from aegisquant.contracts.research import DataSnapshot, Last30DaysResearchRecord, SourceReceipt
from aegisquant.intelligence.source_gateway import LAST30DAYS_TOOL_ID
from aegisquant.security.digests import digest_canonical, sha256_bytes


class Last30DaysAdapterError(ValueError):
    pass


def record_last30days_capture(
    receipt: SourceReceipt,
    body: bytes,
    *,
    snapshot: DataSnapshot,
) -> Last30DaysResearchRecord:
    """Bind a verified gateway capture without retaining its untrusted body."""

    if receipt.tool_id != LAST30DAYS_TOOL_ID:
        raise Last30DaysAdapterError("Last30Days record requires a Last30Days source receipt")
    if sha256_bytes(body) != receipt.content_digest:
        raise Last30DaysAdapterError("Last30Days body does not match its source receipt")
    if snapshot.tenant_id != receipt.tenant_id or snapshot.case_id != receipt.case_id:
        raise Last30DaysAdapterError("snapshot and source receipt must share tenant and case")
    return Last30DaysResearchRecord(
        tenant_id=receipt.tenant_id,
        case_id=receipt.case_id,
        snapshot_id=snapshot.snapshot_id,
        snapshot_manifest_digest=snapshot.manifest_digest,
        source_receipt_digest=digest_canonical(receipt),
        source_content_digest=receipt.content_digest,
        available_at=receipt.captured_at,
    )
