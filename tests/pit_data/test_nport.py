from datetime import UTC, datetime

import pytest

from aegis.pit_data.nport import NPortHolding, nport_archive_url
from aegis.pit_data.sec import SecPITError


def test_nport_url_is_official_and_period_is_validated() -> None:
    assert nport_archive_url("2021Q3").endswith("/2021q3_nport.zip")
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
