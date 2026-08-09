"""Official SEC N-PORT archive capture and conservative holding contracts."""

from __future__ import annotations

import re

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
