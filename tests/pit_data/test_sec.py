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
