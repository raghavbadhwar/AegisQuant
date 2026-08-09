"""Official SEC N-PORT archive capture and conservative holding contracts."""

from __future__ import annotations

import csv
import re
import zipfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from aegis.contracts import RawDocumentReceipt

from .sec import SecPITClient, SecPITError

_QUARTER = re.compile(r"^(20\d{2})Q([1-4])$")


class NPortHolding(BaseModel):
    """N-PORT holding where public disclosure is independent from holding report date."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fund_id: str = Field(min_length=1)
    fund_name: str = Field(min_length=1)
    holding_name: str = Field(min_length=1)
    cusip: str | None = None
    quantity: float | None = None
    value_usd: float | None = None
    report_at: AwareDatetime
    filed_at: AwareDatetime | None = None
    public_available_at: AwareDatetime
    accession: str = Field(min_length=1)
    raw_artifact_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def disclosure_is_causal(self) -> NPortHolding:
        if self.filed_at is not None and self.public_available_at < self.filed_at:
            raise ValueError("N-PORT public availability cannot precede filing")
        return self


def nport_archive_url(period: str) -> str:
    """Return the official SEC quarterly archive URL for `YYYYQ#`."""
    match = _QUARTER.fullmatch(period.upper())
    if match is None:
        raise SecPITError("N-PORT period must use YYYYQ#")
    year, quarter = match.groups()
    return f"https://www.sec.gov/files/dera/data/form-n-port-data-sets/{year.lower()}q{quarter}_nport.zip"


def acquire_nport_archive(client: SecPITClient, period: str) -> RawDocumentReceipt:
    """Capture original official N-PORT zip bytes before any flat-file parsing."""
    url = nport_archive_url(period)
    body = client._fetch(url, "application/zip")
    return client._commit(
        source_id="sec-nport",
        request_id=f"nport-{period.upper()}",
        url=url,
        body=body,
        media_type="application/zip",
    )


def _nport_date(value: str) -> date:
    """Parse the SEC flat-file ISO or ``DD-MON-YYYY`` date encodings."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            return datetime.strptime(value.upper(), "%d-%b-%Y").date()
        except ValueError as exc:
            raise SecPITError("N-PORT date is not a supported SEC encoding") from exc


def _date_at_next_utc_day(value: str) -> datetime:
    """Use next UTC midnight when the archive lacks accepted/public timestamp."""
    return datetime.combine(_nport_date(value) + timedelta(days=1), time.min, tzinfo=UTC)


def normalize_nport_holdings(
    archive_path: str | Path,
    *,
    raw_artifact_id: str,
    series_ids: frozenset[str],
) -> tuple[NPortHolding, ...]:
    """Parse selected official N-PORT holdings without treating report date as public.

    The SEC flat-file archive has a filing date but not a sufficiently precise
    acceptance timestamp in this table.  The assigned availability is therefore
    the following UTC day, a documented conservative policy.
    """
    if not series_ids:
        raise SecPITError("N-PORT normalization requires explicit bounded series IDs")
    path = Path(archive_path).resolve()
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SecPITError("invalid N-PORT archive") from exc
    required = {"SUBMISSION.tsv", "FUND_REPORTED_INFO.tsv", "FUND_REPORTED_HOLDING.tsv"}
    if not required.issubset(archive.namelist()):
        raise SecPITError("N-PORT archive lacks required normalized tables")
    with archive:
        with archive.open("SUBMISSION.tsv") as handle:
            submissions = {
                row["ACCESSION_NUMBER"]: row
                for row in csv.DictReader((line.decode("utf-8") for line in handle), delimiter="\t")
                if row.get("ACCESSION_NUMBER") and row.get("FILING_DATE") and row.get("REPORT_DATE")
            }
        selected: dict[str, tuple[str, str]] = {}
        with archive.open("FUND_REPORTED_INFO.tsv") as handle:
            for row in csv.DictReader((line.decode("utf-8") for line in handle), delimiter="\t"):
                accession = row.get("ACCESSION_NUMBER", "")
                series_id = row.get("SERIES_ID", "")
                if accession in submissions and series_id in series_ids:
                    selected[accession] = (series_id, row.get("SERIES_NAME", series_id))
        output: list[NPortHolding] = []
        with archive.open("FUND_REPORTED_HOLDING.tsv") as handle:
            for row in csv.DictReader((line.decode("utf-8") for line in handle), delimiter="\t"):
                accession = row.get("ACCESSION_NUMBER", "")
                fund = selected.get(accession)
                if fund is None:
                    continue
                submission = submissions[accession]
                try:
                    report_at = datetime.combine(
                        _nport_date(submission["REPORT_DATE"]), time.min, tzinfo=UTC
                    )
                    output.append(
                        NPortHolding(
                            fund_id=fund[0],
                            fund_name=fund[1] or fund[0],
                            holding_name=row["ISSUER_NAME"],
                            cusip=row.get("ISSUER_CUSIP") or None,
                            quantity=float(row["BALANCE"]) if row.get("BALANCE") else None,
                            value_usd=float(row["CURRENCY_VALUE"])
                            if row.get("CURRENCY_VALUE")
                            else None,
                            report_at=report_at,
                            filed_at=_date_at_next_utc_day(submission["FILING_DATE"]),
                            public_available_at=_date_at_next_utc_day(submission["FILING_DATE"]),
                            accession=accession,
                            raw_artifact_id=raw_artifact_id,
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise SecPITError("malformed selected N-PORT holding") from exc
    return tuple(
        sorted(
            output, key=lambda item: (item.public_available_at, item.accession, item.holding_name)
        )
    )
