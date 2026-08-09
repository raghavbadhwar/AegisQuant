"""Narrow SEC EDGAR client for building hashable point-in-time artifacts.

This is an ingestion utility, never a live-trading or decision authority.  It
requires a caller-supplied SEC-compliant User-Agent and preserves raw response
bytes through the existing content-addressed RawStore.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aegis.contracts import FetchedDocument, RawDocumentReceipt
from aegis.sources.raw_store import RawStore

_SEC_DATA_HOST = "https://data.sec.gov"
_SEC_ARCHIVES_HOST = "https://www.sec.gov"
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")


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
        if self.filed_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("SEC filing timestamps must be timezone-aware")
        if self.available_at < self.filed_at:
            raise ValueError("SEC availability cannot precede filing time")
        return self


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
    ) -> None:
        if "@" not in user_agent or len(user_agent) < 8:
            raise SecPITError("SEC client requires a contact-bearing User-Agent")
        self.user_agent = user_agent
        self.raw_store = raw_store
        self._fetch = fetch or self._http_fetch

    def _http_fetch(self, url: str, media_type: str) -> bytes:
        try:
            import httpx
        except ImportError as exc:
            raise SecPITError("httpx is required for SEC PIT acquisition") from exc
        response = httpx.get(
            url,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=30.0,
            follow_redirects=False,
        )
        if response.is_redirect or response.status_code != 200:
            raise SecPITError(f"SEC request failed with status {response.status_code}")
        if len(response.content) > 25_000_000:
            raise SecPITError("SEC response exceeds ingestion limit")
        return response.content

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
            recent = payload["filings"]["recent"]
            ticker = str(payload["tickers"][0])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise SecPITError("invalid SEC submissions payload") from exc
        result: list[SecFiling] = []
        for index, accession in enumerate(recent["accessionNumber"]):
            filed = datetime.fromisoformat(recent["filingDate"][index]).replace(tzinfo=UTC)
            report = recent["reportDate"][index]
            result.append(
                SecFiling(
                    cik=normalized,
                    ticker=ticker,
                    form=recent["form"][index],
                    accession_number=accession,
                    primary_document=recent["primaryDocument"][index],
                    period_end=datetime.fromisoformat(report).replace(tzinfo=UTC)
                    if report
                    else None,
                    filed_at=filed,
                    available_at=filed,
                )
            )
        return tuple(result)

    def filing_document(self, filing: SecFiling) -> RawDocumentReceipt:
        accession = filing.accession_number.replace("-", "")
        document = quote(filing.primary_document, safe="")
        url = f"{_SEC_ARCHIVES_HOST}/Archives/edgar/data/{int(filing.cik)}/{accession}/{document}"
        body = self._fetch(url, "text/html")
        return self._commit(
            source_id="sec-edgar",
            request_id=f"filing-{filing.accession_number}",
            url=url,
            body=body,
            media_type="text/html",
        )
