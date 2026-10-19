from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from aegisquant.contracts.research import DataSnapshot, SourceReceipt
from aegisquant.intelligence.last30days_adapter import (
    LAST30DAYS_TOOL_ID,
    Last30DaysAdapterError,
    record_last30days_capture,
)
from aegisquant.security.digests import sha256_bytes

BODY = b"recorded fixture content"


def snapshot(*, tenant_id: str, case_id: UUID) -> DataSnapshot:
    return DataSnapshot(
        tenant_id=tenant_id,
        case_id=case_id,
        snapshot_id="snapshot-v1",
        manifest_digest="sha256:" + "a" * 64,
        content_digest="sha256:" + "b" * 64,
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        frozen_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def receipt(*, tool_id: str = LAST30DAYS_TOOL_ID) -> SourceReceipt:
    return SourceReceipt(
        tenant_id="tenant-a",
        case_id=uuid4(),
        tool_id=tool_id,
        url="https://recorded.example/report",
        content_digest=sha256_bytes(BODY),
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_recorded_last30days_capture_is_bound_without_a_runtime_transport() -> None:
    source = receipt()
    record = record_last30days_capture(
        source,
        BODY,
        snapshot=snapshot(tenant_id=source.tenant_id, case_id=source.case_id),
    )

    assert record.tenant_id == source.tenant_id
    assert record.case_id == source.case_id
    assert record.source_content_digest == source.content_digest
    assert record.available_at == source.captured_at


def test_recorded_capture_rejects_wrong_tool_body_or_tenant() -> None:
    source = receipt(tool_id="scrapling-public-fetch")
    bound_snapshot = snapshot(tenant_id=source.tenant_id, case_id=source.case_id)
    with pytest.raises(Last30DaysAdapterError, match="Last30Days source receipt"):
        record_last30days_capture(source, BODY, snapshot=bound_snapshot)

    source = source.model_copy(update={"tool_id": LAST30DAYS_TOOL_ID})
    with pytest.raises(Last30DaysAdapterError, match="does not match"):
        record_last30days_capture(source, b"tampered", snapshot=bound_snapshot)
    with pytest.raises(Last30DaysAdapterError, match="share tenant and case"):
        record_last30days_capture(
            source,
            BODY,
            snapshot=snapshot(tenant_id="tenant-b", case_id=source.case_id),
        )
