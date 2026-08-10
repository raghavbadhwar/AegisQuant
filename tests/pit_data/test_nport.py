import hashlib
from datetime import UTC, datetime
from zipfile import ZipFile

import pytest
from typer.testing import CliRunner

from aegis.contracts import RawDocumentReceipt
from aegis.pit_data.builder import PITBuildError, normalize_nport
from aegis.pit_data.nport import (
    NPortHolding,
    _nport_date,
    normalize_nport_holdings,
    nport_archive_url,
)
from aegis.pit_data.sec import SecPITError


def test_nport_url_is_official_and_period_is_validated() -> None:
    assert nport_archive_url("2021Q3").endswith("/2021q3_nport.zip")
    assert _nport_date("31-OCT-2024").isoformat() == "2024-10-31"
    with pytest.raises(SecPITError):
        nport_archive_url("2021-Q3")


def test_nport_holding_never_uses_report_date_as_public_disclosure() -> None:
    with pytest.raises(ValueError, match="availability"):
        NPortHolding(
            fund_id="x",
            fund_name="Fund",
            holding_id="H1",
            holding_name="Holding",
            report_at=datetime(2021, 6, 30, tzinfo=UTC),
            filed_at=datetime(2021, 8, 1, tzinfo=UTC),
            public_available_at=datetime(2021, 7, 1, tzinfo=UTC),
            accession="x",
            raw_artifact_id=f"sec-nport:{'a' * 64}",
            raw_content_hash="a" * 64,
            raw_uri="raw://nport",
            archive_retrieved_at=datetime(2021, 8, 1, tzinfo=UTC),
        )


def test_nport_normalizer_binds_archive_receipt_and_observed_availability(tmp_path) -> None:  # type: ignore[no-untyped-def]
    archive = tmp_path / "nport.zip"
    with ZipFile(archive, "w") as zipped:
        zipped.writestr(
            "SUBMISSION.tsv",
            "ACCESSION_NUMBER\tFILING_DATE\tREPORT_DATE\n0001\t2024-02-14\t2024-01-31\n",
        )
        zipped.writestr(
            "FUND_REPORTED_INFO.tsv",
            "ACCESSION_NUMBER\tSERIES_ID\tSERIES_NAME\n0001\tS0001\tExample Fund\n",
        )
        zipped.writestr(
            "FUND_REPORTED_HOLDING.tsv",
            "ACCESSION_NUMBER\tHOLDING_ID\tISSUER_NAME\tISSUER_CUSIP\tBALANCE\tCURRENCY_VALUE\n"
            "0001\tH1\tApple Inc.\t037833100\t2\t400\n",
        )
    body = archive.read_bytes()
    receipt = RawDocumentReceipt(
        source_id="sec-nport",
        request_id="nport-2024Q1",
        url="https://www.sec.gov/files/dera/data/form-n-port-data-sets/2024q1_nport.zip",
        connector="sec-pit-v1",
        connector_version="sec-pit-v1",
        status_code=200,
        headers={"content-type": "application/zip"},
        fetched_at=datetime(2024, 4, 1, tzinfo=UTC),
        media_type="application/zip",
        content_hash=hashlib.sha256(body).hexdigest(),
        raw_uri=archive.as_posix(),
        byte_length=len(body),
    )
    rows = normalize_nport_holdings(archive, raw_receipt=receipt, series_ids=frozenset({"S0001"}))
    assert rows[0].report_at == datetime(2024, 1, 31, tzinfo=UTC)
    assert rows[0].public_available_at == receipt.fetched_at
    assert rows[0].raw_artifact_id == f"sec-nport:{receipt.content_hash}"
    assert rows[0].raw_content_hash == receipt.content_hash


def test_nport_cli_requires_receipt_instead_of_caller_artifact_id() -> None:
    from apps.cli import app

    result = CliRunner().invoke(app, ["pit", "normalize-nport", "--help"])

    assert result.exit_code == 0
    assert "--receipt" in result.stdout
    assert "--raw-artifact-id" not in result.stdout


def test_nport_normalizer_rejects_archive_receipt_mismatch(tmp_path) -> None:  # type: ignore[no-untyped-def]
    archive = tmp_path / "nport.zip"
    archive.write_bytes(b"not the retained archive")
    receipt = RawDocumentReceipt(
        source_id="sec-nport",
        request_id="nport-2024Q1",
        url="https://www.sec.gov/files/dera/data/form-n-port-data-sets/2024q1_nport.zip",
        connector="sec-pit-v1",
        connector_version="sec-pit-v1",
        status_code=200,
        headers={"content-type": "application/zip"},
        fetched_at=datetime(2024, 4, 1, tzinfo=UTC),
        media_type="application/zip",
        content_hash="b" * 64,
        raw_uri=archive.as_posix(),
        byte_length=len(archive.read_bytes()),
    )

    with pytest.raises(SecPITError, match="does not match raw receipt"):
        normalize_nport_holdings(archive, raw_receipt=receipt, series_ids=frozenset({"S0001"}))


def test_nport_holding_model_copy_revalidates_receipt_timing() -> None:
    holding = NPortHolding(
        fund_id="x",
        fund_name="Fund",
        holding_id="H1",
        holding_name="Holding",
        report_at=datetime(2021, 6, 30, tzinfo=UTC),
        filed_at=datetime(2021, 8, 1, tzinfo=UTC),
        public_available_at=datetime(2021, 8, 2, tzinfo=UTC),
        accession="x",
        raw_artifact_id=f"sec-nport:{'a' * 64}",
        raw_content_hash="a" * 64,
        raw_uri="raw://nport",
        archive_retrieved_at=datetime(2021, 8, 2, tzinfo=UTC),
    )

    with pytest.raises(ValueError):
        holding.model_copy(update={"public_available_at": datetime(2021, 7, 1, tzinfo=UTC)})
    with pytest.raises(ValueError):
        holding.model_copy(update={"unknown": "field"})


def test_nport_persistence_is_idempotent_and_rejects_conflicting_holding_identity(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    archive = tmp_path / "nport.zip"

    def write_archive(value: str) -> RawDocumentReceipt:
        with ZipFile(archive, "w") as zipped:
            zipped.writestr(
                "SUBMISSION.tsv",
                "ACCESSION_NUMBER\tFILING_DATE\tREPORT_DATE\n0001\t2024-02-14\t2024-01-31\n",
            )
            zipped.writestr(
                "FUND_REPORTED_INFO.tsv",
                "ACCESSION_NUMBER\tSERIES_ID\tSERIES_NAME\n0001\tS0001\tExample Fund\n",
            )
            zipped.writestr(
                "FUND_REPORTED_HOLDING.tsv",
                "ACCESSION_NUMBER\tHOLDING_ID\tISSUER_NAME\tCURRENCY_VALUE\n"
                f"0001\tH1\tApple Inc.\t{value}\n",
            )
        body = archive.read_bytes()
        return RawDocumentReceipt(
            source_id="sec-nport",
            request_id="nport-2024Q1",
            url="https://www.sec.gov/files/dera/data/form-n-port-data-sets/2024q1_nport.zip",
            connector="sec-pit-v1",
            connector_version="sec-pit-v1",
            status_code=200,
            headers={"content-type": "application/zip"},
            fetched_at=datetime(2024, 4, 1, tzinfo=UTC),
            media_type="application/zip",
            content_hash=hashlib.sha256(body).hexdigest(),
            raw_uri=archive.as_posix(),
            byte_length=len(body),
        )

    receipt = write_archive("400")
    first = normalize_nport(
        tmp_path / "lake",
        archive,
        raw_receipt=receipt,
        series_ids=frozenset({"S0001"}),
    )
    assert (
        normalize_nport(
            tmp_path / "lake",
            archive,
            raw_receipt=receipt,
            series_ids=frozenset({"S0001"}),
        )
        == first
    )
    assert len((tmp_path / "lake/normalized/nport_holdings.jsonl").read_text().splitlines()) == 1

    conflicting_receipt = write_archive("999")
    with pytest.raises(PITBuildError, match="conflicting immutable N-PORT holding"):
        normalize_nport(
            tmp_path / "lake",
            archive,
            raw_receipt=conflicting_receipt,
            series_ids=frozenset({"S0001"}),
        )


@pytest.mark.parametrize(
    ("table", "body"),
    [
        (
            "SUBMISSION.tsv",
            "ACCESSION_NUMBER\tFILING_DATE\tREPORT_DATE\n"
            "0001\t2024-02-14\t2024-01-31\n0001\t2024-03-20\t2024-02-29\n",
        ),
        (
            "FUND_REPORTED_INFO.tsv",
            "ACCESSION_NUMBER\tSERIES_ID\tSERIES_NAME\n0001\tS0001\tFund A\n0001\tS0001\tFund B\n",
        ),
        (
            "FUND_REPORTED_HOLDING.tsv",
            "ACCESSION_NUMBER\tHOLDING_ID\tISSUER_NAME\n0001\tH1\tApple\n0001\tH1\tApple\n",
        ),
    ],
)
def test_nport_normalizer_rejects_duplicate_primary_rows(tmp_path, table: str, body: str) -> None:  # type: ignore[no-untyped-def]
    archive = tmp_path / "nport.zip"
    tables = {
        "SUBMISSION.tsv": (
            "ACCESSION_NUMBER\tFILING_DATE\tREPORT_DATE\n0001\t2024-02-14\t2024-01-31\n"
        ),
        "FUND_REPORTED_INFO.tsv": (
            "ACCESSION_NUMBER\tSERIES_ID\tSERIES_NAME\n0001\tS0001\tFund A\n"
        ),
        "FUND_REPORTED_HOLDING.tsv": (
            "ACCESSION_NUMBER\tHOLDING_ID\tISSUER_NAME\n0001\tH1\tApple\n"
        ),
    }
    tables[table] = body
    with ZipFile(archive, "w") as zipped:
        for name, content in tables.items():
            zipped.writestr(name, content)
    raw = archive.read_bytes()
    receipt = RawDocumentReceipt(
        source_id="sec-nport",
        request_id="nport-2024Q1",
        url="https://www.sec.gov/files/dera/data/form-n-port-data-sets/2024q1_nport.zip",
        connector="sec-pit-v1",
        connector_version="sec-pit-v1",
        status_code=200,
        headers={"content-type": "application/zip"},
        fetched_at=datetime(2024, 4, 1, tzinfo=UTC),
        media_type="application/zip",
        content_hash=hashlib.sha256(raw).hexdigest(),
        raw_uri=archive.as_posix(),
        byte_length=len(raw),
    )

    with pytest.raises(SecPITError, match="duplicate N-PORT"):
        normalize_nport_holdings(archive, raw_receipt=receipt, series_ids=frozenset({"S0001"}))


@pytest.mark.parametrize("value", ["NaN", "inf", "-inf"])
def test_nport_normalizer_rejects_non_finite_values(tmp_path, value: str) -> None:  # type: ignore[no-untyped-def]
    archive = tmp_path / "nport.zip"
    with ZipFile(archive, "w") as zipped:
        zipped.writestr(
            "SUBMISSION.tsv",
            "ACCESSION_NUMBER\tFILING_DATE\tREPORT_DATE\n0001\t2024-02-14\t2024-01-31\n",
        )
        zipped.writestr(
            "FUND_REPORTED_INFO.tsv",
            "ACCESSION_NUMBER\tSERIES_ID\tSERIES_NAME\n0001\tS0001\tFund A\n",
        )
        zipped.writestr(
            "FUND_REPORTED_HOLDING.tsv",
            f"ACCESSION_NUMBER\tHOLDING_ID\tISSUER_NAME\tBALANCE\n0001\tH1\tApple\t{value}\n",
        )
    raw = archive.read_bytes()
    receipt = RawDocumentReceipt(
        source_id="sec-nport",
        request_id="nport-2024Q1",
        url="https://www.sec.gov/files/dera/data/form-n-port-data-sets/2024q1_nport.zip",
        connector="sec-pit-v1",
        connector_version="sec-pit-v1",
        status_code=200,
        headers={"content-type": "application/zip"},
        fetched_at=datetime(2024, 4, 1, tzinfo=UTC),
        media_type="application/zip",
        content_hash=hashlib.sha256(raw).hexdigest(),
        raw_uri=archive.as_posix(),
        byte_length=len(raw),
    )

    with pytest.raises(SecPITError, match="malformed selected N-PORT holding"):
        normalize_nport_holdings(archive, raw_receipt=receipt, series_ids=frozenset({"S0001"}))
