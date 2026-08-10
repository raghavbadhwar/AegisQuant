from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegis.pit_data import (
    SecFiling,
    SecPITClient,
    SecPITError,
    parse_archived_xbrl_facts,
    select_available_filings,
)
from aegis.sources import RawStore


def test_sec_filing_rejects_accession_from_another_cik() -> None:
    with pytest.raises(ValueError, match="accession CIK"):
        SecFiling(
            cik="0000320193",
            ticker="AAPL",
            form="10-Q",
            accession_number="0000789019-21-000001",
            primary_document="aapl.htm",
            filed_at=datetime(2021, 8, 10, tzinfo=UTC),
            available_at=datetime(2021, 8, 11, tzinfo=UTC),
        )


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


def test_archived_submission_binds_xbrl_fact_to_accession_and_acceptance_time() -> None:
    filing = SecFiling(
        cik="0000320193",
        ticker="AAPL",
        form="10-Q",
        accession_number="0000320193-21-000001",
        primary_document="aapl.htm",
        period_end=datetime(2021, 6, 30, tzinfo=UTC),
        filed_at=datetime(2021, 8, 10, tzinfo=UTC),
        available_at=datetime(2021, 8, 11, tzinfo=UTC),
    )
    submission = b"""<SEC-DOCUMENT>
<ACCESSION-NUMBER>0000320193-21-000001
<CENTRAL-INDEX-KEY>0000320193
<ACCEPTANCE-DATETIME>20210810173000
<DOCUMENT>
<TYPE>EX-101.INS
<FILENAME>aapl-20210630.xml
<TEXT>
<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:us-gaap="http://fasb.org/us-gaap/2024">
  <xbrli:context id="duration">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2021-04-01</xbrli:startDate>
      <xbrli:endDate>2021-06-30</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <us-gaap:Revenues contextRef="duration" unitRef="usd" decimals="-6">10</us-gaap:Revenues>
</xbrli:xbrl>
</TEXT>
</DOCUMENT>
"""

    facts = parse_archived_xbrl_facts(filing, submission, tags=("Revenues",))

    assert len(facts) == 1
    assert facts[0].accession_number == filing.accession_number
    assert facts[0].taxonomy == "us-gaap"
    assert facts[0].unit == "USD"
    assert facts[0].value == 10.0
    assert facts[0].period_start == datetime(2021, 4, 1, tzinfo=UTC)
    assert facts[0].period_end == datetime(2021, 6, 30, tzinfo=UTC)
    assert facts[0].available_at == datetime(2021, 8, 10, 21, 30, tzinfo=UTC)


def test_archived_submission_rejects_ambiguous_acceptance_time() -> None:
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
<ACCEPTANCE-DATETIME>20210810173100
<DOCUMENT><TYPE>EX-101.INS<TEXT>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" />
</TEXT></DOCUMENT>"""

    with pytest.raises(SecPITError, match="exactly one acceptance timestamp"):
        parse_archived_xbrl_facts(filing, submission)


def test_archived_submission_rejects_acceptance_time_outside_header() -> None:
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
<DOCUMENT><TYPE>EX-101.INS<TEXT>
<ACCEPTANCE-DATETIME>20210810173000
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" />
</TEXT></DOCUMENT>"""

    with pytest.raises(SecPITError, match="acceptance timestamp"):
        parse_archived_xbrl_facts(filing, submission)


def test_archived_submission_header_must_match_filing_identity() -> None:
    filing = SecFiling(
        cik="0000320193",
        ticker="AAPL",
        form="10-Q",
        accession_number="0000320193-21-000001",
        primary_document="aapl.htm",
        filed_at=datetime(2021, 8, 10, tzinfo=UTC),
        available_at=datetime(2021, 8, 11, tzinfo=UTC),
    )
    submission = b"""<ACCESSION-NUMBER>0000320193-21-000999
<CENTRAL-INDEX-KEY>0000320193
<ACCEPTANCE-DATETIME>20210810173000
<DOCUMENT><TYPE>EX-101.INS<TEXT>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" />
</TEXT></DOCUMENT>"""

    with pytest.raises(SecPITError, match="header identity"):
        parse_archived_xbrl_facts(filing, submission)


@pytest.mark.parametrize(
    "header",
    (
        b"<ACCESSION-NUMBER>0000320193-21-000001evil\n"
        b"<CENTRAL-INDEX-KEY>0000320193\n<ACCEPTANCE-DATETIME>20210810173000",
        b"<ACCESSION-NUMBER>0000320193-21-000001\n"
        b"<CENTRAL-INDEX-KEY>0000320193evil\n<ACCEPTANCE-DATETIME>20210810173000",
        b"<ACCESSION-NUMBER>0000320193-21-000001\n"
        b"<CENTRAL-INDEX-KEY>0000320193\n<ACCEPTANCE-DATETIME>202108101730009",
    ),
)
def test_archived_submission_rejects_header_value_suffixes(header: bytes) -> None:
    filing = SecFiling(
        cik="0000320193",
        ticker="AAPL",
        form="10-Q",
        accession_number="0000320193-21-000001",
        primary_document="aapl.htm",
        filed_at=datetime(2021, 8, 10, tzinfo=UTC),
        available_at=datetime(2021, 8, 11, tzinfo=UTC),
    )
    submission = (
        header
        + b"\n<DOCUMENT><TYPE>EX-101.INS<TEXT>"
        + b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" />'
        + b"</TEXT></DOCUMENT>"
    )

    with pytest.raises(SecPITError):
        parse_archived_xbrl_facts(filing, submission)


def test_archived_submission_rejects_duplicate_context_ids() -> None:
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
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">
<xbrli:context id="duplicate"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
</xbrli:entity><xbrli:period><xbrli:instant>2021-06-30</xbrli:instant></xbrli:period>
</xbrli:context><xbrli:context id="duplicate"><xbrli:entity>
<xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier></xbrli:entity><xbrli:period>
<xbrli:instant>2021-03-31</xbrli:instant></xbrli:period></xbrli:context>
</xbrli:xbrl></TEXT></DOCUMENT>"""

    with pytest.raises(SecPITError, match="context IDs must be unique"):
        parse_archived_xbrl_facts(filing, submission)


def test_archived_submission_rejects_duplicate_unit_ids() -> None:
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
<DOCUMENT><TYPE>EX-101.INS<TEXT><xbrli:xbrl
 xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
<xbrli:unit id="u"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<xbrli:unit id="u"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
</xbrli:xbrl></TEXT></DOCUMENT>"""

    with pytest.raises(SecPITError, match="unit IDs must be unique"):
        parse_archived_xbrl_facts(filing, submission)


def test_archived_submission_rejects_ambiguous_duplicate_facts() -> None:
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
<DOCUMENT><TYPE>EX-101.INS<TEXT><xbrli:xbrl
 xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:us-gaap="http://fasb.org/us-gaap/2021-01-31">
<xbrli:context id="c"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
</xbrli:entity><xbrli:period><xbrli:instant>2021-06-30</xbrli:instant></xbrli:period>
</xbrli:context><xbrli:unit id="u"><xbrli:measure>iso4217:USD</xbrli:measure>
</xbrli:unit><us-gaap:Assets contextRef="c" unitRef="u">10</us-gaap:Assets>
<us-gaap:Assets contextRef="c" unitRef="u">99</us-gaap:Assets>
</xbrli:xbrl></TEXT></DOCUMENT>"""

    with pytest.raises(SecPITError, match="facts must be unique"):
        parse_archived_xbrl_facts(filing, submission)


def test_archived_submission_rejects_non_xsd_period_date() -> None:
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
<DOCUMENT><TYPE>EX-101.INS<TEXT><xbrli:xbrl
 xmlns:xbrli="http://www.xbrl.org/2003/instance">
<xbrli:context id="c"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
</xbrli:entity><xbrli:period><xbrli:instant>2021-06-30T23:00:00-05:00
</xbrli:instant></xbrli:period></xbrli:context>
</xbrli:xbrl></TEXT></DOCUMENT>"""

    with pytest.raises(SecPITError, match="period date"):
        parse_archived_xbrl_facts(filing, submission)


@pytest.mark.parametrize(
    ("trusted", "spoofed"),
    (
        (b"http://www.sec.gov/CIK", b"urn:attacker:entity"),
        (b"http://www.xbrl.org/2003/iso4217", b"urn:attacker:unit"),
        (b"http://fasb.org/us-gaap/2021-01-31", b"urn:attacker:taxonomy"),
        (b"http://fasb.org/us-gaap/2021-01-31", b"http://fasb.org/us-gaap/9999"),
        (
            b"http://fasb.org/us-gaap/2021-01-31",
            b"http://fasb.org/us-gaap/2024-99-99",
        ),
        (b"iso4217:USD", b"xbrli:USD"),
        (b"iso4217:USD", b"xbrli:anything"),
    ),
)
def test_archived_submission_rejects_spoofed_qname_provenance(
    trusted: bytes, spoofed: bytes
) -> None:
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
<DOCUMENT><TYPE>EX-101.INS<TEXT><xbrli:xbrl
 xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:us-gaap="http://fasb.org/us-gaap/2021-01-31">
<xbrli:context id="c"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">
0000320193</xbrli:identifier></xbrli:entity><xbrli:period>
<xbrli:instant>2021-06-30</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:unit id="u"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<us-gaap:Assets contextRef="c" unitRef="u">10</us-gaap:Assets>
</xbrli:xbrl></TEXT></DOCUMENT>""".replace(trusted, spoofed)

    with pytest.raises(SecPITError, match=r"provenance|scheme|namespace|QName"):
        parse_archived_xbrl_facts(filing, submission)


def test_archived_submission_quarantines_dimensional_facts() -> None:
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
 xmlns:foo="urn:custom-dimension"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:us-gaap="http://fasb.org/us-gaap/2021-01-31">
<xbrli:context id="segment"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
<xbrli:segment><foo:member>custom</foo:member></xbrli:segment></xbrli:entity><xbrli:period>
<xbrli:instant>2021-06-30</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:unit id="u"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<us-gaap:Assets contextRef="segment" unitRef="u">10</us-gaap:Assets>
</xbrli:xbrl></TEXT></DOCUMENT>"""

    assert parse_archived_xbrl_facts(filing, submission) == ()
