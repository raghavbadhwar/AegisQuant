from datetime import UTC, datetime
from zipfile import ZipFile

import pytest

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
            holding_name="Holding",
            report_at=datetime(2021, 6, 30, tzinfo=UTC),
            filed_at=datetime(2021, 8, 1, tzinfo=UTC),
            public_available_at=datetime(2021, 7, 1, tzinfo=UTC),
            accession="x",
            raw_artifact_id="x",
        )


def test_nport_normalizer_uses_next_day_availability_not_portfolio_date(tmp_path) -> None:  # type: ignore[no-untyped-def]
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
            "ACCESSION_NUMBER\tISSUER_NAME\tISSUER_CUSIP\tBALANCE\tCURRENCY_VALUE\n"
            "0001\tApple Inc.\t037833100\t2\t400\n",
        )
    rows = normalize_nport_holdings(
        archive, raw_artifact_id="sec-nport:hash", series_ids=frozenset({"S0001"})
    )
    assert rows[0].report_at == datetime(2024, 1, 31, tzinfo=UTC)
    assert rows[0].public_available_at == datetime(2024, 2, 15, tzinfo=UTC)
