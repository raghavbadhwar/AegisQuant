import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegis.contracts import RawDocumentReceipt, canonical_json
from aegis.pit_data import PITArtifact, SecFiling
from aegis.pit_data.builder import bootstrap


def test_bootstrap_creates_only_empty_local_lake_structure(tmp_path: Path) -> None:
    root = bootstrap(tmp_path / "pit")
    assert (root / "raw" / "sec").is_dir()
    assert (root / "normalized").is_dir()
    assert (root / "snapshots").is_dir()
    assert "Synthetic data is prohibited" in (root / "README.md").read_text()


def test_ingestion_rejects_inverted_date_window(tmp_path: Path) -> None:
    from datetime import date

    from aegis.pit_data.builder import PITBuildError, ingest_sec

    with pytest.raises(PITBuildError, match="end"):
        ingest_sec(
            tmp_path,
            "AegisQuant test@example.com",
            ("AAPL",),
            filing_start=date(2022, 1, 1),
            filing_end=date(2021, 1, 1),
        )


def test_sec_ingestion_uses_archived_accession_xbrl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from aegis.pit_data import builder

    filing = SecFiling(
        cik="0000320193",
        ticker="AAPL",
        form="10-Q",
        accession_number="0000320193-21-000001",
        primary_document="aapl.htm",
        filed_at=datetime(2021, 8, 10, tzinfo=UTC),
        available_at=datetime(2021, 8, 11, tzinfo=UTC),
    )
    submission = b"""<ACCESSION-NUMBER>0000320193-21-000001
<CENTRAL-INDEX-KEY>0000320193
<ACCEPTANCE-DATETIME>20210810173000
<DOCUMENT><TYPE>EX-101.INS<TEXT>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:us-gaap="http://fasb.org/us-gaap/2021-01-31">
<xbrli:context id="c"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
</xbrli:entity><xbrli:period><xbrli:instant>2021-06-30</xbrli:instant></xbrli:period>
</xbrli:context><xbrli:unit id="u"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<us-gaap:Assets contextRef="c" unitRef="u">10</us-gaap:Assets></xbrli:xbrl>
</TEXT></DOCUMENT>"""
    receipt = RawDocumentReceipt(
        source_id="sec-edgar",
        request_id="filing-0000320193-21-000001",
        url="https://www.sec.gov/Archives/example.txt",
        connector="sec-pit-v1",
        connector_version="sec-pit-v1",
        status_code=200,
        headers={"content-type": "text/plain"},
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        media_type="text/plain",
        content_hash=hashlib.sha256(submission).hexdigest(),
        raw_uri="raw://submission",
        byte_length=len(submission),
    )

    class FakeClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def ticker_cik_map(self) -> dict[str, str]:
            return {"AAPL": filing.cik}

        def submissions(self, _cik: str) -> tuple[SecFiling, ...]:
            return (filing,)

        def filing_submission(self, _filing: SecFiling) -> tuple[RawDocumentReceipt, bytes]:
            return receipt, submission

    monkeypatch.setattr(builder, "SecPITClient", FakeClient)

    artifacts = builder.ingest_sec(tmp_path, "AegisQuant test@example.com", ("AAPL",))

    assert artifacts[0].accepted_at == datetime(2021, 8, 10, 21, 30, tzinfo=UTC)
    assert (
        PITArtifact.model_validate_json(
            (tmp_path / "normalized" / "artifact_ledger.jsonl").read_text().strip()
        ).raw_path
        == receipt.raw_uri
    )
    fact = json.loads(
        (tmp_path / "normalized" / "fundamental_fact_versions.jsonl").read_text().strip()
    )
    assert fact["concept"] == "Assets"
    assert fact["accession"] == filing.accession_number


def test_artifact_ledger_rejects_conflicting_receipt_for_same_accession(tmp_path: Path) -> None:
    from aegis.pit_data.builder import PITBuildError, _append_immutable

    first = PITArtifact(
        artifact_id="sec:0000320193:0000320193-21-000001",
        source="SEC_EDGAR",
        source_record_id="0000320193-21-000001",
        entity_id="AAPL",
        artifact_type="filing",
        available_at=datetime(2021, 8, 10, 21, 30, tzinfo=UTC),
        ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_path="raw://first",
        sha256="a" * 64,
        parser_version="sec-archived-xbrl-v1",
    )
    ledger = tmp_path / "artifacts.jsonl"
    _append_immutable(ledger, (first,))
    conflicting = first.model_copy(update={"raw_path": "raw://second", "sha256": "b" * 64})

    with pytest.raises(PITBuildError, match="conflicting immutable artifact"):
        _append_immutable(ledger, (conflicting,))

    assert PITArtifact.model_validate_json(ledger.read_text().strip()) == first


def test_artifact_ledger_rejects_preexisting_duplicate_ids(tmp_path: Path) -> None:
    from aegis.pit_data.builder import PITBuildError, _append_immutable

    first = PITArtifact(
        artifact_id="sec:0000320193:0000320193-21-000001",
        source="SEC_EDGAR",
        source_record_id="0000320193-21-000001",
        entity_id="AAPL",
        artifact_type="filing",
        available_at=datetime(2021, 8, 10, 21, 30, tzinfo=UTC),
        ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_path="raw://first",
        sha256="a" * 64,
        parser_version="sec-archived-xbrl-v1",
    )
    conflicting = first.model_copy(update={"raw_path": "raw://second", "sha256": "b" * 64})
    ledger = tmp_path / "artifacts.jsonl"
    ledger.write_text(f"{canonical_json(first)}\n{canonical_json(conflicting)}\n")

    with pytest.raises(PITBuildError, match="conflicting immutable artifact"):
        _append_immutable(ledger, ())


def test_artifact_ledger_is_idempotent_for_same_receipt_retrieved_later(tmp_path: Path) -> None:
    from aegis.pit_data.builder import _append_immutable

    first = PITArtifact(
        artifact_id="sec:0000320193:0000320193-21-000001",
        source="SEC_EDGAR",
        source_record_id="0000320193-21-000001",
        entity_id="AAPL",
        artifact_type="filing",
        available_at=datetime(2021, 8, 10, 21, 30, tzinfo=UTC),
        ingested_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_path="raw://same",
        sha256="a" * 64,
        parser_version="sec-archived-xbrl-v1",
    )
    ledger = tmp_path / "artifacts.jsonl"
    _append_immutable(ledger, (first,))

    _append_immutable(
        ledger,
        (first.model_copy(update={"ingested_at": datetime(2026, 1, 2, tzinfo=UTC)}),),
    )

    assert len(ledger.read_text().splitlines()) == 1


def test_sec_ingestion_rejects_receipt_that_does_not_match_submission_bytes() -> None:
    from aegis.pit_data.builder import PITBuildError, _require_receipt_body

    body = b"archived submission"
    receipt = RawDocumentReceipt(
        source_id="sec-edgar",
        request_id="filing-0000320193-21-000001",
        url="https://www.sec.gov/Archives/example.txt",
        connector="sec-pit-v1",
        connector_version="sec-pit-v1",
        status_code=200,
        headers={"content-type": "text/plain"},
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        media_type="text/plain",
        content_hash="b" * 64,
        raw_uri="raw://submission",
        byte_length=len(body),
    )

    with pytest.raises(PITBuildError, match="receipt does not match"):
        _require_receipt_body(receipt, body)
