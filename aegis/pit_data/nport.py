"""Official SEC N-PORT archive capture and conservative holding contracts."""

from __future__ import annotations

import csv
import hashlib
import re
import zipfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import RawDocumentReceipt
from aegis.contracts._base import CandidateContractModel

from .sec import SecPITClient, SecPITError

_QUARTER = re.compile(r"^(20\d{2})Q([1-4])$")


class NPortHolding(CandidateContractModel):
    """N-PORT holding where public disclosure is independent from holding report date."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fund_id: str = Field(min_length=1)
    fund_name: str = Field(min_length=1)
    holding_id: str = Field(min_length=1)
    holding_name: str = Field(min_length=1)
    cusip: str | None = None
    quantity: float | None = Field(default=None, allow_inf_nan=False)
    value_usd: float | None = Field(default=None, allow_inf_nan=False)
    report_at: AwareDatetime
    filed_at: AwareDatetime | None = None
    public_available_at: AwareDatetime
    accession: str = Field(min_length=1)
    raw_artifact_id: str = Field(min_length=1)
    raw_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_uri: str = Field(min_length=1)
    archive_retrieved_at: AwareDatetime
    availability_policy: Literal["sec_quarterly_archive_observed_v1"] = (
        "sec_quarterly_archive_observed_v1"
    )

    @model_validator(mode="after")
    def disclosure_is_causal(self) -> NPortHolding:
        if self.filed_at is not None and self.public_available_at < self.filed_at:
            raise ValueError("N-PORT public availability cannot precede filing")
        if self.public_available_at < self.archive_retrieved_at:
            raise ValueError("N-PORT public availability cannot precede archive retrieval")
        if self.raw_artifact_id != f"sec-nport:{self.raw_content_hash}":
            raise ValueError("N-PORT raw artifact ID must bind the archive content hash")
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


def _date_at_utc_day(value: str) -> datetime:
    return datetime.combine(_nport_date(value), time.min, tzinfo=UTC)


def _date_at_next_utc_day(value: str) -> datetime:
    """Use next UTC midnight when the archive lacks accepted/public timestamp."""
    return _date_at_utc_day(value) + timedelta(days=1)


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def normalize_nport_holdings(
    archive_path: str | Path,
    *,
    raw_receipt: RawDocumentReceipt,
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
    if raw_receipt.source_id != "sec-nport" or raw_receipt.media_type != "application/zip":
        raise SecPITError("N-PORT receipt source or media type is invalid")
    try:
        archive_hash, archive_size = _file_sha256(path)
        retained_hash, retained_size = _file_sha256(Path(raw_receipt.raw_uri))
    except OSError as exc:
        raise SecPITError("N-PORT receipt source is unavailable") from exc
    if (
        archive_hash != raw_receipt.content_hash
        or retained_hash != raw_receipt.content_hash
        or archive_size != raw_receipt.byte_length
        or retained_size != raw_receipt.byte_length
    ):
        raise SecPITError("N-PORT archive does not match raw receipt")
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SecPITError("invalid N-PORT archive") from exc
    required = {"SUBMISSION.tsv", "FUND_REPORTED_INFO.tsv", "FUND_REPORTED_HOLDING.tsv"}
    if not required.issubset(archive.namelist()):
        raise SecPITError("N-PORT archive lacks required normalized tables")
    with archive:
        with archive.open("SUBMISSION.tsv") as handle:
            submissions: dict[str, dict[str, str]] = {}
            for row in csv.DictReader((line.decode("utf-8") for line in handle), delimiter="\t"):
                accession = row.get("ACCESSION_NUMBER", "")
                if not accession or not row.get("FILING_DATE") or not row.get("REPORT_DATE"):
                    continue
                if accession in submissions:
                    raise SecPITError("duplicate N-PORT submission")
                submissions[accession] = row
        selected: dict[str, tuple[str, str]] = {}
        with archive.open("FUND_REPORTED_INFO.tsv") as handle:
            for row in csv.DictReader((line.decode("utf-8") for line in handle), delimiter="\t"):
                accession = row.get("ACCESSION_NUMBER", "")
                series_id = row.get("SERIES_ID", "")
                if accession in submissions and series_id in series_ids:
                    if accession in selected:
                        raise SecPITError("duplicate N-PORT fund information")
                    selected[accession] = (series_id, row.get("SERIES_NAME", series_id))
        output: list[NPortHolding] = []
        holding_ids: set[tuple[str, str]] = set()
        with archive.open("FUND_REPORTED_HOLDING.tsv") as handle:
            for row in csv.DictReader((line.decode("utf-8") for line in handle), delimiter="\t"):
                accession = row.get("ACCESSION_NUMBER", "")
                fund = selected.get(accession)
                if fund is None:
                    continue
                holding_key = (accession, row.get("HOLDING_ID", ""))
                if holding_key in holding_ids:
                    raise SecPITError("duplicate N-PORT holding")
                holding_ids.add(holding_key)
                submission = submissions[accession]
                try:
                    report_at = datetime.combine(
                        _nport_date(submission["REPORT_DATE"]), time.min, tzinfo=UTC
                    )
                    output.append(
                        NPortHolding(
                            fund_id=fund[0],
                            fund_name=fund[1] or fund[0],
                            holding_id=row["HOLDING_ID"],
                            holding_name=row["ISSUER_NAME"],
                            cusip=row.get("ISSUER_CUSIP") or None,
                            quantity=float(row["BALANCE"]) if row.get("BALANCE") else None,
                            value_usd=float(row["CURRENCY_VALUE"])
                            if row.get("CURRENCY_VALUE")
                            else None,
                            report_at=report_at,
                            # FILING_DATE is date-only.  Preserve that stated date
                            # separately and expose it only at the following UTC day.
                            filed_at=_date_at_utc_day(submission["FILING_DATE"]),
                            public_available_at=max(
                                _date_at_next_utc_day(submission["FILING_DATE"]),
                                raw_receipt.fetched_at,
                            ),
                            accession=accession,
                            raw_artifact_id=f"sec-nport:{raw_receipt.content_hash}",
                            raw_content_hash=raw_receipt.content_hash,
                            raw_uri=raw_receipt.raw_uri,
                            archive_retrieved_at=raw_receipt.fetched_at,
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise SecPITError("malformed selected N-PORT holding") from exc
    return tuple(
        sorted(
            output, key=lambda item: (item.public_available_at, item.accession, item.holding_name)
        )
    )
