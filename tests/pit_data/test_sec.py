from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegis.pit_data import SecPITClient, SecPITError, select_available_filings
from aegis.sources import RawStore


def test_sec_submission_artifacts_are_raw_captured_and_cutoff_bound(tmp_path: Path) -> None:
    payload = {
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000069", "0000320193-24-000123"],
                "filingDate": ["2024-05-03", "2024-08-02"],
                "reportDate": ["2024-03-30", "2024-06-29"],
                "form": ["10-Q", "10-Q"],
                "primaryDocument": ["aapl-20240330.htm", "aapl-20240629.htm"],
            }
        },
    }

    def fetch(url: str, media_type: str) -> bytes:
        assert url == "https://data.sec.gov/submissions/CIK0000320193.json"
        assert media_type == "application/json"
        return json.dumps(payload).encode()

    client = SecPITClient("AegisQuant test@example.com", RawStore(tmp_path / "raw"), fetch=fetch)
    filings = client.submissions("320193")
    assert [
        item.form for item in select_available_filings(filings, datetime(2024, 6, 1, tzinfo=UTC))
    ] == ["10-Q"]
    assert list((tmp_path / "raw").glob("**/*")) != []


def test_sec_client_requires_contact_user_agent() -> None:
    with pytest.raises(SecPITError, match="User-Agent"):
        SecPITClient("AegisQuant", RawStore("/tmp/aegis-unused"))


def test_company_facts_preserves_versions_for_later_as_of_selection(tmp_path: Path) -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "val": 10,
                                "form": "10-Q",
                                "accn": "0000320193-21-000001",
                                "filed": "2021-08-10",
                                "end": "2021-06-30",
                            },
                            {
                                "val": 9.6,
                                "form": "10-Q/A",
                                "accn": "0000320193-22-000001",
                                "filed": "2022-02-17",
                                "end": "2021-06-30",
                            },
                        ]
                    }
                }
            }
        }
    }
    client = SecPITClient(
        "AegisQuant test@example.com",
        RawStore(tmp_path / "raw"),
        fetch=lambda _url, _type: json.dumps(payload).encode(),
    )
    facts = client.company_facts("320193", tags=("Revenues",))
    visible_2021 = [x.value for x in facts if x.available_at <= datetime(2021, 12, 1, tzinfo=UTC)]
    visible_2022 = [x.value for x in facts if x.available_at <= datetime(2022, 3, 1, tzinfo=UTC)]
    assert visible_2021 == [10.0]
    assert visible_2022 == [10.0, 9.6]


def test_submission_skips_rows_without_primary_document_but_preserves_raw_index(
    tmp_path: Path,
) -> None:
    payload = {
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000069"],
                "filingDate": ["2024-05-03"],
                "reportDate": ["2024-03-30"],
                "form": ["4"],
                "primaryDocument": [""],
            }
        },
    }
    client = SecPITClient(
        "AegisQuant test@example.com",
        RawStore(tmp_path / "raw"),
        fetch=lambda _url, _type: json.dumps(payload).encode(),
    )
    assert client.submissions("320193") == ()
    assert list((tmp_path / "raw").glob("**/*.json"))


def test_date_only_sec_fields_are_not_visible_at_start_of_filing_day(tmp_path: Path) -> None:
    payload = {
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000069"],
                "filingDate": ["2024-05-03"],
                "reportDate": ["2024-03-30"],
                "form": ["10-Q"],
                "primaryDocument": ["aapl.htm"],
            }
        },
    }
    client = SecPITClient(
        "AegisQuant test@example.com",
        RawStore(tmp_path / "raw"),
        fetch=lambda _url, _type: json.dumps(payload).encode(),
    )
    filing = client.submissions("320193")[0]
    assert filing.filed_at == datetime(2024, 5, 3, tzinfo=UTC)
    assert filing.available_at == datetime(2024, 5, 4, tzinfo=UTC)
    assert not select_available_filings((filing,), datetime(2024, 5, 3, 23, 59, tzinfo=UTC))


def test_company_facts_retains_duration_start_dates(tmp_path: Path) -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenue": {
                    "units": {
                        "USD": [
                            {
                                "val": 10,
                                "form": "10-Q",
                                "accn": "0000320193-24-000001",
                                "filed": "2024-05-03",
                                "start": "2024-01-01",
                                "end": "2024-03-30",
                            },
                            {
                                "val": 30,
                                "form": "10-Q",
                                "accn": "0000320193-24-000001",
                                "filed": "2024-08-02",
                                "start": "2024-01-01",
                                "end": "2024-06-29",
                            },
                            {
                                "val": 20,
                                "form": "10-Q",
                                "accn": "0000320193-24-000001",
                                "filed": "2024-08-02",
                                "start": "2024-03-31",
                                "end": "2024-06-29",
                            },
                        ]
                    }
                }
            }
        }
    }
    client = SecPITClient(
        "AegisQuant test@example.com",
        RawStore(tmp_path / "raw"),
        fetch=lambda _url, _type: json.dumps(payload).encode(),
    )
    facts = client.company_facts("320193")
    assert facts[-1].available_at == datetime(2024, 8, 3, tzinfo=UTC)
    assert {item.period_start for item in facts} == {
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 3, 31, tzinfo=UTC),
    }
