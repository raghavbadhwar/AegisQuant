"""Narrow SEC EDGAR client for building hashable point-in-time artifacts.

This is an ingestion utility, never a live-trading or decision authority.  It
requires a caller-supplied SEC-compliant User-Agent and preserves raw response
bytes through the existing content-addressed RawStore.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import cast
from urllib.parse import quote
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aegis.contracts import FetchedDocument, RawDocumentReceipt
from aegis.sources.raw_store import RawStore

_SEC_DATA_HOST = "https://data.sec.gov"
_SEC_ARCHIVES_HOST = "https://www.sec.gov"
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_SUBMISSION_FILE = re.compile(r"^[A-Za-z0-9_.-]+\.json$")
_HEADER_FLAGS = re.IGNORECASE | re.MULTILINE
_ACCEPTANCE_DATETIME = re.compile(rb"^<ACCEPTANCE-DATETIME>[ \t]*(\d{14})[ \t]*\r?$", _HEADER_FLAGS)
_ACCESSION_HEADER = re.compile(
    rb"^<ACCESSION-NUMBER>[ \t]*(\d{10}-\d{2}-\d{6})[ \t]*\r?$", _HEADER_FLAGS
)
_CIK_HEADER = re.compile(rb"^<CENTRAL-INDEX-KEY>[ \t]*(\d{1,10})[ \t]*\r?$", _HEADER_FLAGS)
_XBRL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DOCUMENT = re.compile(rb"<DOCUMENT>(.*?)</DOCUMENT>", re.IGNORECASE | re.DOTALL)
_DOCUMENT_TYPE = re.compile(rb"<TYPE>\s*([^\r\n<]+)", re.IGNORECASE)
_DOCUMENT_TEXT = re.compile(rb"<TEXT>\s*(.*?)\s*</TEXT>", re.IGNORECASE | re.DOTALL)
_XBRLI = "http://www.xbrl.org/2003/instance"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_SEC_CIK_SCHEME = "http://www.sec.gov/CIK"
_ISO4217 = "http://www.xbrl.org/2003/iso4217"
_US_GAAP_NAMESPACES = frozenset(
    [f"http://fasb.org/us-gaap/{year}-01-31" for year in range(2009, 2022)]
    + [f"http://fasb.org/us-gaap/{year}" for year in range(2022, 2027)]
)


def _date_only_available_at(value: str) -> datetime:
    """Return a conservative availability time for SEC date-only fields.

    EDGAR submissions and Company Facts expose ``filingDate``/``filed`` as a
    calendar date, not the acceptance timestamp.  Midnight on that date would
    make a filing visible before it could have been accepted.  The next UTC
    day is a deliberately conservative cutoff until an acceptance-time source
    is captured.
    """
    try:
        filed_day = datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError as exc:
        raise SecPITError("invalid SEC date-only timestamp") from exc
    return filed_day + timedelta(days=1)


class SecPITError(RuntimeError):
    """SEC PIT ingestion cannot safely continue."""


class SecFiling(BaseModel):
    """Immutable filing identity and availability boundary from EDGAR submissions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cik: str = Field(pattern=r"^\d{10}$")
    ticker: str = Field(min_length=1)
    form: str = Field(min_length=1)
    accession_number: str
    primary_document: str = Field(min_length=1)
    period_end: datetime | None = None
    filed_at: datetime
    available_at: datetime

    @field_validator("accession_number")
    @classmethod
    def valid_accession(cls, value: str) -> str:
        if not _ACCESSION.fullmatch(value):
            raise ValueError("invalid SEC accession number")
        return value

    @model_validator(mode="after")
    def availability_is_causal(self) -> SecFiling:
        if self.accession_number[:10] != self.cik:
            raise ValueError("SEC accession CIK must match filing CIK")
        if self.filed_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("SEC filing timestamps must be timezone-aware")
        if self.available_at < self.filed_at:
            raise ValueError("SEC availability cannot precede filing time")
        return self


class SecFactObservation(BaseModel):
    """Reported XBRL value with accession-level, non-overwritable PIT lineage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cik: str = Field(pattern=r"^\d{10}$")
    taxonomy: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    value: float
    form: str = Field(min_length=1)
    accession_number: str
    period_start: datetime | None = None
    period_end: datetime
    filed_at: datetime
    available_at: datetime

    @field_validator("accession_number")
    @classmethod
    def fact_accession_is_valid(cls, value: str) -> str:
        if not _ACCESSION.fullmatch(value):
            raise ValueError("invalid SEC accession number")
        return value

    @model_validator(mode="after")
    def fact_is_causal(self) -> SecFactObservation:
        if self.accession_number[:10] != self.cik:
            raise ValueError("SEC fact accession CIK must match fact CIK")
        if self.available_at < self.filed_at:
            raise ValueError("fact availability cannot precede filing")
        return self


def archived_acceptance_time(submission: bytes, filing: SecFiling) -> datetime:
    first_document = _DOCUMENT.search(submission)
    header = submission[: first_document.start()] if first_document else submission
    accessions = _ACCESSION_HEADER.findall(header)
    ciks = _CIK_HEADER.findall(header)
    if (
        len(accessions) != 1
        or len(ciks) != 1
        or accessions[0].decode("ascii") != filing.accession_number
        or ciks[0].decode("ascii").zfill(10) != filing.cik
    ):
        raise SecPITError("archived SEC header identity does not match filing")
    matches = _ACCEPTANCE_DATETIME.findall(header)
    if len(matches) != 1:
        raise SecPITError("archived SEC submission requires exactly one acceptance timestamp")
    try:
        local = datetime.strptime(matches[0].decode("ascii"), "%Y%m%d%H%M%S").replace(
            tzinfo=ZoneInfo("America/New_York")
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise SecPITError("invalid archived SEC acceptance timestamp") from exc
    if local.date() != filing.filed_at.date():
        raise SecPITError("archived SEC acceptance date does not match filing")
    return local.astimezone(UTC)


def _archived_xbrl_instance(submission: bytes) -> bytes:
    if len(submission) > 25_000_000:
        raise SecPITError("archived SEC submission exceeds parsing limit")
    instances: list[bytes] = []
    for document in _DOCUMENT.findall(submission):
        document_type = _DOCUMENT_TYPE.search(document)
        if document_type is None or document_type.group(1).strip().upper() != b"EX-101.INS":
            continue
        text = _DOCUMENT_TEXT.search(document)
        if text is None:
            raise SecPITError("archived XBRL instance lacks document text")
        instances.append(text.group(1).strip())
    if len(instances) != 1:
        raise SecPITError("archived SEC submission requires exactly one XBRL instance")
    return instances[0]


def _xbrl_date(value: str) -> datetime:
    if not _XBRL_DATE.fullmatch(value):
        raise SecPITError("invalid archived XBRL period date")
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise SecPITError("invalid archived XBRL period date") from exc


def parse_archived_xbrl_facts(
    filing: SecFiling,
    submission: bytes,
    *,
    tags: tuple[str, ...] = (),
) -> tuple[SecFactObservation, ...]:
    """Parse consolidated numeric facts from one raw accession submission.

    This parser accepts only the original ``EX-101.INS`` document, an exact
    acceptance timestamp, simple units, and non-dimensional contexts. It fails
    closed instead of guessing across ambiguous instance documents or contexts.
    """

    available_at = archived_acceptance_time(submission, filing)
    instance = _archived_xbrl_instance(submission)
    namespaces: dict[str, str] = {}
    namespace_by_prefix: dict[str, str] = {}
    try:
        for _, item in ElementTree.iterparse(BytesIO(instance), events=("start-ns",)):
            namespace_prefix, namespace_uri = cast(tuple[str, str], item)
            if (
                namespace_prefix in namespace_by_prefix
                and namespace_by_prefix[namespace_prefix] != namespace_uri
            ):
                raise SecPITError("archived XBRL namespace prefix is ambiguous")
            if (namespace_prefix == "iso4217" and namespace_uri != _ISO4217) or (
                namespace_prefix == "us-gaap" and namespace_uri not in _US_GAAP_NAMESPACES
            ):
                raise SecPITError("archived XBRL namespace provenance is invalid")
            namespace_by_prefix[namespace_prefix] = namespace_uri
            namespaces[namespace_uri] = namespace_prefix
        root = ElementTree.fromstring(instance)
    except (ElementTree.ParseError, ValueError) as exc:
        raise SecPITError("invalid archived XBRL instance") from exc
    if root.tag != f"{{{_XBRLI}}}xbrl":
        raise SecPITError("archived XBRL instance has invalid root")

    contexts: dict[str, tuple[datetime | None, datetime]] = {}
    context_ids: set[str] = set()
    for context in root.findall(f"{{{_XBRLI}}}context"):
        context_id = context.get("id", "")
        if not context_id:
            raise SecPITError("archived XBRL context lacks ID")
        if context_id in context_ids:
            raise SecPITError("archived XBRL context IDs must be unique")
        context_ids.add(context_id)
        if (
            context.find(f".//{{{_XBRLI}}}segment") is not None
            or context.find(f".//{{{_XBRLI}}}scenario") is not None
        ):
            continue
        identifier = context.find(f".//{{{_XBRLI}}}identifier")
        if identifier is None or not identifier.text:
            raise SecPITError("archived XBRL context lacks entity identifier")
        if identifier.get("scheme") != _SEC_CIK_SCHEME:
            raise SecPITError("archived XBRL entity identifier scheme is invalid")
        if identifier.text.strip().zfill(10) != filing.cik:
            raise SecPITError("archived XBRL context entity does not match filing")
        period = context.find(f"{{{_XBRLI}}}period")
        if period is None:
            raise SecPITError("archived XBRL context lacks period")
        instant = period.find(f"{{{_XBRLI}}}instant")
        start = period.find(f"{{{_XBRLI}}}startDate")
        end = period.find(f"{{{_XBRLI}}}endDate")
        if instant is not None and instant.text:
            contexts[context_id] = (None, _xbrl_date(instant.text.strip()))
        elif start is not None and start.text and end is not None and end.text:
            contexts[context_id] = (
                _xbrl_date(start.text.strip()),
                _xbrl_date(end.text.strip()),
            )
        else:
            raise SecPITError("archived XBRL context has unsupported period")

    units: dict[str, str] = {}
    unit_ids: set[str] = set()
    for unit in root.findall(f"{{{_XBRLI}}}unit"):
        unit_id = unit.get("id", "")
        if unit_id in unit_ids:
            raise SecPITError("archived XBRL unit IDs must be unique")
        unit_ids.add(unit_id)
        measures = unit.findall(f"{{{_XBRLI}}}measure")
        if not unit_id or len(measures) != 1 or not measures[0].text:
            continue
        measure = measures[0].text.strip()
        unit_prefix, separator, local_name = measure.partition(":")
        namespace = namespace_by_prefix.get(unit_prefix)
        if (
            not separator
            or not local_name
            or (namespace == _ISO4217 and not re.fullmatch(r"[A-Z]{3}", local_name))
            or (namespace == _XBRLI and local_name not in {"pure", "shares"})
        ):
            raise SecPITError("archived XBRL unit QName is invalid")
        if namespace not in {_ISO4217, _XBRLI}:
            raise SecPITError("archived XBRL unit namespace is unsupported")
        units[unit_id] = local_name

    requested = set(tags)
    observations: list[SecFactObservation] = []
    fact_keys: set[tuple[str, str, str, datetime | None, datetime]] = set()
    for fact in root:
        if fact.get(f"{{{_XSI}}}nil", "false").lower() == "true":
            continue
        context_ref = fact.get("contextRef")
        unit_ref = fact.get("unitRef")
        if context_ref not in contexts or unit_ref not in units or fact.text is None:
            continue
        namespace, separator, tag = (
            fact.tag[1:].partition("}") if fact.tag.startswith("{") else ("", "", fact.tag)
        )
        if not separator or not tag or (requested and tag not in requested):
            continue
        taxonomy_prefix = namespaces.get(namespace, "")
        if not taxonomy_prefix:
            raise SecPITError("archived XBRL fact taxonomy prefix is unavailable")
        taxonomy = "us-gaap" if namespace in _US_GAAP_NAMESPACES else namespace
        try:
            value = float(fact.text.strip())
        except ValueError as exc:
            raise SecPITError("archived XBRL numeric fact is invalid") from exc
        if not math.isfinite(value):
            raise SecPITError("archived XBRL numeric fact must be finite")
        period_start, period_end = contexts[context_ref]
        fact_key = (taxonomy, tag, units[unit_ref], period_start, period_end)
        if fact_key in fact_keys:
            raise SecPITError("archived XBRL facts must be unique by concept, unit, and period")
        fact_keys.add(fact_key)
        observations.append(
            SecFactObservation(
                cik=filing.cik,
                taxonomy=taxonomy,
                tag=tag,
                unit=units[unit_ref],
                value=value,
                form=filing.form,
                accession_number=filing.accession_number,
                period_start=period_start,
                period_end=period_end,
                filed_at=filing.filed_at,
                available_at=available_at,
            )
        )
    return tuple(
        sorted(observations, key=lambda item: (item.period_end, item.taxonomy, item.tag, item.unit))
    )


def select_available_filings(
    filings: tuple[SecFiling, ...], as_of: datetime
) -> tuple[SecFiling, ...]:
    """Return only artifacts that were available at the simulation clock."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise SecPITError("PIT cutoff must be timezone-aware")
    return tuple(
        sorted(
            (item for item in filings if item.available_at <= as_of),
            key=lambda item: (item.available_at, item.accession_number),
        )
    )


class SecPITClient:
    """Allowlisted EDGAR downloader that commits raw bytes before interpretation."""

    def __init__(
        self,
        user_agent: str,
        raw_store: RawStore,
        *,
        fetch: Callable[[str, str], bytes] | None = None,
        max_requests_per_second: float = 5.0,
        max_attempts: int = 3,
    ) -> None:
        if "@" not in user_agent or len(user_agent) < 8:
            raise SecPITError("SEC client requires a contact-bearing User-Agent")
        if max_requests_per_second <= 0 or max_requests_per_second > 10:
            raise SecPITError("SEC request rate must be within (0, 10] requests per second")
        if max_attempts < 1 or max_attempts > 5:
            raise SecPITError("SEC request attempts must be within [1, 5]")
        self.user_agent = user_agent
        self.raw_store = raw_store
        self.max_attempts = max_attempts
        self._minimum_interval = 1.0 / max_requests_per_second
        self._last_request = 0.0
        self._fetch = fetch or self._http_fetch

    def _http_fetch(self, url: str, media_type: str) -> bytes:
        try:
            import httpx
        except ImportError as exc:
            raise SecPITError("httpx is required for SEC PIT acquisition") from exc
        for attempt in range(self.max_attempts):
            elapsed = time.monotonic() - self._last_request
            if elapsed < self._minimum_interval:
                time.sleep(self._minimum_interval - elapsed)
            try:
                response = httpx.get(
                    url,
                    headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
                    timeout=30.0,
                    follow_redirects=False,
                )
            except httpx.HTTPError as exc:
                if attempt + 1 == self.max_attempts:
                    raise SecPITError("SEC network request failed after retries") from exc
                time.sleep(0.5 * (2**attempt))
                continue
            self._last_request = time.monotonic()
            if response.is_redirect:
                raise SecPITError("SEC redirect is forbidden by the source allowlist")
            if response.status_code == 200:
                maximum_bytes = 1_000_000_000 if media_type == "application/zip" else 25_000_000
                if len(response.content) > maximum_bytes:
                    raise SecPITError("SEC response exceeds ingestion limit")
                return response.content
            if (
                response.status_code not in {429, 500, 502, 503, 504}
                or attempt + 1 == self.max_attempts
            ):
                raise SecPITError(f"SEC request failed with status {response.status_code}")
            time.sleep(0.5 * (2**attempt))
        raise AssertionError("unreachable SEC retry state")

    def _commit(
        self, *, source_id: str, request_id: str, url: str, body: bytes, media_type: str
    ) -> RawDocumentReceipt:
        return self.raw_store.commit(
            FetchedDocument(
                source_id=source_id,
                request_id=request_id,
                url=url,
                connector="sec-pit-v1",
                connector_version="sec-pit-v1",
                status_code=200,
                headers={"content-type": media_type},
                body=body,
                fetched_at=datetime.now(UTC),
                media_type=media_type,
            )
        )

    def submissions(self, cik: str) -> tuple[SecFiling, ...]:
        normalized = cik.zfill(10)
        if not normalized.isdigit() or len(normalized) != 10:
            raise SecPITError("CIK must be numeric")
        url = f"{_SEC_DATA_HOST}/submissions/CIK{normalized}.json"
        body = self._fetch(url, "application/json")
        self._commit(
            source_id="sec-edgar",
            request_id=f"submissions-{normalized}",
            url=url,
            body=body,
            media_type="application/json",
        )
        try:
            payload = json.loads(body)
            ticker = str(payload["tickers"][0])
            batches = [payload["filings"]["recent"]]
            historical_files = payload["filings"].get("files", [])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise SecPITError("invalid SEC submissions payload") from exc
        for entry in historical_files:
            name = entry.get("name") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not _SUBMISSION_FILE.fullmatch(name):
                raise SecPITError("unsafe historical SEC submission filename")
            history_url = f"{_SEC_DATA_HOST}/submissions/{name}"
            history_body = self._fetch(history_url, "application/json")
            self._commit(
                source_id="sec-edgar",
                request_id=f"submissions-{normalized}-{name}",
                url=history_url,
                body=history_body,
                media_type="application/json",
            )
            try:
                batches.append(json.loads(history_body))
            except json.JSONDecodeError as exc:
                raise SecPITError("invalid historical SEC submissions payload") from exc
        result: list[SecFiling] = []
        for recent in batches:
            try:
                accessions = recent["accessionNumber"]
                for index, accession in enumerate(accessions):
                    primary_document = recent["primaryDocument"][index]
                    if not isinstance(primary_document, str) or not primary_document:
                        # The original submission index remains raw-captured; without a
                        # primary document this narrow artifact downloader cannot
                        # construct a stable archive-document URL.
                        continue
                    filed = datetime.fromisoformat(recent["filingDate"][index]).replace(tzinfo=UTC)
                    report = recent["reportDate"][index]
                    result.append(
                        SecFiling(
                            cik=normalized,
                            ticker=ticker,
                            form=recent["form"][index],
                            accession_number=accession,
                            primary_document=primary_document,
                            period_end=datetime.fromisoformat(report).replace(tzinfo=UTC)
                            if report
                            else None,
                            filed_at=filed,
                            available_at=_date_only_available_at(recent["filingDate"][index]),
                        )
                    )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise SecPITError("malformed SEC filing entry") from exc
        return tuple(sorted(result, key=lambda item: (item.filed_at, item.accession_number)))

    def ticker_cik_map(self) -> dict[str, str]:
        """Fetch the official SEC ticker/CIK mapping and raw-capture its bytes."""
        url = f"{_SEC_ARCHIVES_HOST}/files/company_tickers.json"
        body = self._fetch(url, "application/json")
        self._commit(
            source_id="sec-edgar",
            request_id="company-tickers",
            url=url,
            body=body,
            media_type="application/json",
        )
        try:
            records = json.loads(body).values()
            result = {str(row["ticker"]).upper(): str(row["cik_str"]).zfill(10) for row in records}
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SecPITError("invalid SEC ticker mapping payload") from exc
        if not result:
            raise SecPITError("SEC ticker mapping is empty")
        return result

    def company_facts(
        self, cik: str, *, tags: tuple[str, ...] = ()
    ) -> tuple[SecFactObservation, ...]:
        """Fetch Company Facts while retaining every filing version, including restatements."""
        normalized = cik.zfill(10)
        if not normalized.isdigit() or len(normalized) != 10:
            raise SecPITError("CIK must be numeric")
        url = f"{_SEC_DATA_HOST}/api/xbrl/companyfacts/CIK{normalized}.json"
        body = self._fetch(url, "application/json")
        self._commit(
            source_id="sec-edgar",
            request_id=f"companyfacts-{normalized}",
            url=url,
            body=body,
            media_type="application/json",
        )
        try:
            facts = json.loads(body)["facts"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SecPITError("invalid SEC companyfacts payload") from exc
        requested = set(tags)
        observations: list[SecFactObservation] = []
        for taxonomy, taxonomy_facts in facts.items():
            for tag, payload in taxonomy_facts.items():
                if requested and tag not in requested:
                    continue
                for unit, rows in payload.get("units", {}).items():
                    for row in rows:
                        try:
                            filed = datetime.fromisoformat(row["filed"]).replace(tzinfo=UTC)
                            period_end = datetime.fromisoformat(row["end"]).replace(tzinfo=UTC)
                            period_start = (
                                datetime.fromisoformat(row["start"]).replace(tzinfo=UTC)
                                if row.get("start")
                                else None
                            )
                            observations.append(
                                SecFactObservation(
                                    cik=normalized,
                                    taxonomy=taxonomy,
                                    tag=tag,
                                    unit=unit,
                                    value=float(row["val"]),
                                    form=row["form"],
                                    accession_number=row["accn"],
                                    period_start=period_start,
                                    period_end=period_end,
                                    filed_at=filed,
                                    available_at=_date_only_available_at(row["filed"]),
                                )
                            )
                        except (KeyError, TypeError, ValueError) as exc:
                            raise SecPITError("malformed SEC fact observation") from exc
        return tuple(
            sorted(
                observations,
                key=lambda item: (item.available_at, item.accession_number, item.tag),
            )
        )

    def filing_document(self, filing: SecFiling) -> RawDocumentReceipt:
        accession = filing.accession_number.replace("-", "")
        document = quote(filing.primary_document, safe="")
        url = f"{_SEC_ARCHIVES_HOST}/Archives/edgar/data/{int(filing.cik)}/{accession}/{document}"
        try:
            body = self._fetch(url, "text/html")
        except SecPITError as exc:
            if "redirect" not in str(exc):
                raise
            # SEC may route some primary-document paths through an interactive
            # viewer. Preserve the canonical complete submitted filing instead.
            archive_root = f"{_SEC_ARCHIVES_HOST}/Archives/edgar/data/{int(filing.cik)}"
            url = f"{archive_root}/{accession}/{accession}.txt"
            body = self._fetch(url, "text/plain")
        return self._commit(
            source_id="sec-edgar",
            request_id=f"filing-{filing.accession_number}",
            url=url,
            body=body,
            media_type="text/html",
        )

    def filing_submission(self, filing: SecFiling) -> tuple[RawDocumentReceipt, bytes]:
        """Raw-capture the complete accession submission used for XBRL parsing."""
        accession = filing.accession_number.replace("-", "")
        archive_root = f"{_SEC_ARCHIVES_HOST}/Archives/edgar/data/{int(filing.cik)}"
        url = f"{archive_root}/{accession}/{accession}.txt"
        body = self._fetch(url, "text/plain")
        receipt = self._commit(
            source_id="sec-edgar",
            request_id=f"filing-{filing.accession_number}",
            url=url,
            body=body,
            media_type="text/plain",
        )
        return receipt, body
