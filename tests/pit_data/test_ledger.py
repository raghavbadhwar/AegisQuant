from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegis.pit_data import PITArtifact, PITAvailabilityLedger, PITLedgerError, load_snapshot


def artifact(identifier: str, available: datetime, digest: str) -> PITArtifact:
    return PITArtifact(
        artifact_id=identifier,
        source="SEC_EDGAR",
        source_record_id=identifier,
        entity_id="AAPL",
        security_id="us:AAPL",
        artifact_type="filing",
        form="10-Q",
        accession="0000320193-21-000001",
        period_end=datetime(2021, 6, 30, tzinfo=UTC),
        filed_at=available,
        available_at=available,
        ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_path="raw/aa/file.html",
        sha256=digest,
        parser_version="sec-pit-v1",
    )


def test_snapshot_time_gate_and_immutable_provenance(tmp_path: Path) -> None:
    old = artifact("old", datetime(2021, 8, 1, tzinfo=UTC), "a" * 64)
    future = artifact("future", datetime(2021, 9, 20, tzinfo=UTC), "b" * 64)
    ledger = PITAvailabilityLedger((future, old))
    root = ledger.write_snapshot(
        tmp_path, datetime(2021, 9, 15, tzinfo=UTC), ("AAPL",), dataset_version="sec-v1"
    )
    manifest, rows = load_snapshot(root)
    assert manifest.artifact_ids == ("old",)
    assert tuple(item.artifact_id for item in rows) == ("old",)
    with pytest.raises(PITLedgerError, match="immutable"):
        ledger.write_snapshot(
            tmp_path, datetime(2021, 9, 15, tzinfo=UTC), ("AAPL",), dataset_version="sec-v1"
        )


def test_artifact_cannot_claim_availability_before_filing() -> None:
    with pytest.raises(ValueError, match="availability"):
        PITArtifact(
            artifact_id="x",
            source="SEC_EDGAR",
            source_record_id="x",
            entity_id="AAPL",
            artifact_type="filing",
            filed_at=datetime(2021, 8, 2, tzinfo=UTC),
            available_at=datetime(2021, 8, 1, tzinfo=UTC),
            ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
            raw_path="raw",
            sha256="a" * 64,
            parser_version="test",
        )
