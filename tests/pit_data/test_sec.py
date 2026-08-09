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
