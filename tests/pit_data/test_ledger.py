from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegis.pit_data import (
    PITArtifact,
    PITAvailabilityLedger,
    PITLedgerError,
    SecurityMasterRecord,
    load_snapshot,
)
from aegis.pit_data.nport import NPortHolding


def security(tmp_path: Path) -> SecurityMasterRecord:
    source = tmp_path / "security-history-v1.json"
    source.write_bytes(b'{"source":"test security history"}')
    return SecurityMasterRecord(
        canonical_security_id="us:AAPL",
        ticker="AAPL",
        issuer="Apple Inc.",
        valid_from=datetime(1900, 1, 1, tzinfo=UTC),
        source="test",
        source_version="v1",
        source_record_id="security-history-v1:AAPL",
        source_available_at=datetime(2020, 1, 1, tzinfo=UTC),
        source_content_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        source_raw_uri=source.as_posix(),
    )


def test_security_mapping_requires_raw_source_receipt_lineage() -> None:
    with pytest.raises(ValueError):
        SecurityMasterRecord(
            canonical_security_id="us:AAPL",
            ticker="AAPL",
            issuer="Apple Inc.",
            valid_from=datetime(1980, 12, 12, tzinfo=UTC),
            source="test",
            source_version="v1",
        )


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
    ledger = PITAvailabilityLedger((future, old), (security(tmp_path),))
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


def test_equivalent_snapshots_have_identical_world_hash_despite_build_time(tmp_path: Path) -> None:
    item = artifact("old", datetime(2021, 8, 1, tzinfo=UTC), "a" * 64)
    ledger = PITAvailabilityLedger((item,), (security(tmp_path),))
    first_path = ledger.write_snapshot(
        tmp_path / "one", datetime(2021, 9, 15, tzinfo=UTC), ("AAPL",), dataset_version="sec-v1"
    )
    second_path = ledger.write_snapshot(
        tmp_path / "two", datetime(2021, 9, 15, tzinfo=UTC), ("AAPL",), dataset_version="sec-v1"
    )
    first, _ = load_snapshot(first_path)
    second, _ = load_snapshot(second_path)
    assert first.manifest_hash == second.manifest_hash


def test_snapshot_excludes_nport_holdings_not_yet_public(tmp_path: Path) -> None:
    ledger = PITAvailabilityLedger(
        (artifact("old", datetime(2021, 8, 1, tzinfo=UTC), "a" * 64),),
        (security(tmp_path),),
    )
    holding = NPortHolding(
        fund_id="S1",
        fund_name="Fund",
        holding_name="Apple",
        report_at=datetime(2021, 6, 30, tzinfo=UTC),
        public_available_at=datetime(2021, 9, 16, tzinfo=UTC),
        accession="accession",
        raw_artifact_id="raw",
    )
    snapshot = ledger.write_snapshot(
        tmp_path,
        datetime(2021, 9, 15, tzinfo=UTC),
        ("AAPL",),
        dataset_version="sec-v1",
        fund_holdings=(holding,),
    )
    assert (snapshot / "fund_holdings.jsonl").read_text() == ""


def test_snapshot_includes_historical_security_mapping_for_ticker_universe(tmp_path: Path) -> None:
    source = tmp_path / "sec-security-history.json"
    source.write_bytes(b'{"source":"SEC security history"}')
    security = SecurityMasterRecord(
        canonical_security_id="sec:0000320193",
        ticker="AAPL",
        cik="0000320193",
        issuer="Apple",
        valid_from=datetime(1900, 1, 1, tzinfo=UTC),
        source="SEC_EDGAR",
        source_version="v1",
        source_record_id="security-history-v1:AAPL",
        source_available_at=datetime(2020, 1, 1, tzinfo=UTC),
        source_content_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        source_raw_uri=source.as_posix(),
    )
    ledger = PITAvailabilityLedger(
        (artifact("old", datetime(2021, 8, 1, tzinfo=UTC), "a" * 64),), (security,)
    )
    snapshot = ledger.write_snapshot(
        tmp_path, datetime(2021, 9, 15, tzinfo=UTC), ("AAPL",), dataset_version="sec-v1"
    )
    assert "sec:0000320193" in (snapshot / "security_master.jsonl").read_text()


def test_snapshot_excludes_security_mapping_not_yet_source_available(tmp_path: Path) -> None:
    future_mapping = security(tmp_path).model_copy(
        update={"source_available_at": datetime(2021, 9, 16, tzinfo=UTC)}
    )
    ledger = PITAvailabilityLedger(
        (artifact("old", datetime(2021, 8, 1, tzinfo=UTC), "a" * 64),),
        (future_mapping,),
    )

    with pytest.raises(PITLedgerError, match="applicable historical security mapping"):
        ledger.write_snapshot(
            tmp_path,
            datetime(2021, 9, 15, tzinfo=UTC),
            ("AAPL",),
            dataset_version="sec-v1",
        )

    assert {item.name for item in tmp_path.iterdir()} == {"security-history-v1.json"}


def test_security_master_rejects_overlapping_ticker_history(tmp_path: Path) -> None:
    first = security(tmp_path)
    second = first.model_copy(
        update={
            "canonical_security_id": "us:AAPL-successor",
            "source_record_id": "security-history-v1:AAPL-successor",
            "valid_from": datetime(2020, 1, 1, tzinfo=UTC),
        }
    )

    with pytest.raises(PITLedgerError, match="overlapping security mapping"):
        PITAvailabilityLedger((), (first, second))


def test_load_snapshot_rejects_artifact_hash_drift(tmp_path: Path) -> None:
    ledger = PITAvailabilityLedger(
        (artifact("old", datetime(2021, 8, 1, tzinfo=UTC), "a" * 64),),
        (security(tmp_path),),
    )
    snapshot = ledger.write_snapshot(
        tmp_path, datetime(2021, 9, 15, tzinfo=UTC), ("AAPL",), dataset_version="sec-v1"
    )
    artifacts = snapshot / "artifacts.jsonl"
    artifacts.write_text(
        artifacts.read_text().replace('"sha256":"' + "a" * 64, '"sha256":"' + "b" * 64)
    )
    with pytest.raises(PITLedgerError, match="hash mismatch"):
        load_snapshot(snapshot)


def test_load_snapshot_rejects_security_mapping_drift(tmp_path: Path) -> None:
    ledger = PITAvailabilityLedger(
        (artifact("old", datetime(2021, 8, 1, tzinfo=UTC), "a" * 64),),
        (security(tmp_path),),
    )
    snapshot = ledger.write_snapshot(
        tmp_path, datetime(2021, 9, 15, tzinfo=UTC), ("AAPL",), dataset_version="sec-v1"
    )
    mappings = snapshot / "security_master.jsonl"
    mappings.write_text(mappings.read_text().replace("Apple Inc.", "Altered Issuer"))

    with pytest.raises(PITLedgerError, match="security mapping hash mismatch"):
        load_snapshot(snapshot)


def test_snapshot_retains_and_verifies_security_source_bytes(tmp_path: Path) -> None:
    mapping = security(tmp_path)
    ledger = PITAvailabilityLedger(
        (artifact("old", datetime(2021, 8, 1, tzinfo=UTC), "a" * 64),), (mapping,)
    )
    snapshot = ledger.write_snapshot(
        tmp_path / "snapshots",
        datetime(2021, 9, 15, tzinfo=UTC),
        ("AAPL",),
        dataset_version="sec-v1",
    )
    retained = snapshot / "security_sources" / f"{mapping.source_content_hash}.bin"

    assert retained.read_bytes() == Path(mapping.source_raw_uri).read_bytes()
    retained.write_bytes(b"tampered")
    with pytest.raises(PITLedgerError, match="security source hash mismatch"):
        load_snapshot(snapshot)


def test_snapshot_manifest_model_copy_revalidates_security_lineage(tmp_path: Path) -> None:
    mapping = security(tmp_path)
    ledger = PITAvailabilityLedger(
        (artifact("old", datetime(2021, 8, 1, tzinfo=UTC), "a" * 64),), (mapping,)
    )
    snapshot = ledger.write_snapshot(
        tmp_path / "snapshots",
        datetime(2021, 9, 15, tzinfo=UTC),
        ("AAPL",),
        dataset_version="sec-v1",
    )
    manifest, _ = load_snapshot(snapshot)

    with pytest.raises(ValueError):
        manifest.model_copy(update={"security_record_ids": manifest.security_record_ids * 2})
    with pytest.raises(ValueError):
        manifest.model_copy(update={"unknown": "field"})
    with pytest.raises(ValueError):
        manifest.model_copy(update={"manifest_hash": "f" * 64})
