"""Typed source-intelligence requests and manifests."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from ._base import ContractModel

SourceType = Literal[
    "local_snapshot",
    "official_api",
    "licensed_api",
    "official_web",
    "rss",
    "social",
    "community",
    "crawler",
    "manual_upload",
]
SourceMode = Literal["replay", "historical", "live_research"]


class SourceManifest(ContractModel):
    source_id: Annotated[str, Field(min_length=1)]
    display_name: Annotated[str, Field(min_length=1)]
    source_type: SourceType
    domains: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=list)
    information_types: list[str] = Field(default_factory=list)
    live_safe: bool
    historical_safe: bool
    point_in_time_safe: bool
    requires_auth: bool
    credential_scope: str | None = None
    licence_classification: Annotated[str, Field(min_length=1)]
    obey_robots: bool = True
    minimum_interval_seconds: int = Field(ge=0)
    max_pages_per_job: int = Field(gt=0)
    max_depth: int = Field(ge=0)
    retention_policy: Annotated[str, Field(min_length=1)]
    parser_profile: Annotated[str, Field(min_length=1)]
    reliability_prior: float = Field(ge=0, le=1, allow_inf_nan=False)
    version: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def validate_domains_and_credentials(self) -> SourceManifest:
        normalized = [domain.strip().lower().lstrip(".") for domain in self.domains]
        if not normalized or any(
            not domain or "://" in domain or "/" in domain for domain in normalized
        ):
            raise ValueError("source domains must be normalized hostnames")
        if len(normalized) != len(set(normalized)):
            raise ValueError("source domains must be unique")
        if self.requires_auth != bool(self.credential_scope):
            raise ValueError("credential scope must match requires_auth")
        object.__setattr__(self, "domains", normalized)
        return self


class SourceRequest(ContractModel):
    case_id: Annotated[str, Field(min_length=1)]
    entity_ids: list[str] = Field(default_factory=list)
    information_type: Annotated[str, Field(min_length=1)]
    query: Annotated[str, Field(min_length=1)]
    as_of: AwareDatetime
    mode: SourceMode
    freshness: timedelta | None = None
    corroboration_required: bool = False
    max_sources: int = Field(gt=0)
    max_cost_usd: float = Field(ge=0, allow_inf_nan=False)


class SourcePlan(ContractModel):
    request_id: Annotated[str, Field(min_length=1)]
    case_id: Annotated[str, Field(min_length=1)]
    source_ids: list[str] = Field(min_length=1)
    acquisition_methods: list[str] = Field(min_length=1)
    mode: Literal["live_research"]
    as_of: AwareDatetime
    planner_version: Annotated[str, Field(min_length=1)]


class ScrapeJob(ContractModel):
    job_id: Annotated[str, Field(min_length=1)]
    source_id: Annotated[str, Field(min_length=1)]
    url: Annotated[str, Field(min_length=1)]
    purpose: Annotated[str, Field(min_length=1)]
    extraction_schema: Annotated[str, Field(min_length=1)]
    mode: Literal["static", "dynamic"]
    as_of: AwareDatetime
    domain_allowlist: list[str] = Field(min_length=1)
    maximum_pages: int = Field(gt=0)
    maximum_depth: int = Field(ge=0)
    timeout_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def url_must_be_allowlisted(self) -> ScrapeJob:
        from urllib.parse import urlparse

        parsed = urlparse(self.url)
        host = (parsed.hostname or "").lower()
        allowed = {domain.lower().lstrip(".") for domain in self.domain_allowlist}
        if parsed.scheme not in {"http", "https"} or not any(
            host == domain or host.endswith(f".{domain}") for domain in allowed
        ):
            raise ValueError("scrape URL is outside the domain allowlist")
        return self


class SourceAttempt(ContractModel):
    source_id: Annotated[str, Field(min_length=1)]
    attempted_at: AwareDatetime
    success: bool
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    stale: bool = False
    parser_failed: bool = False
    blocked: bool = False
    citation_useful: bool = False
    contradicted: bool = False


class SourceHealthSnapshot(ContractModel):
    source_id: Annotated[str, Field(min_length=1)]
    as_of: AwareDatetime
    attempts: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    median_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    stale_frequency: float = Field(ge=0, le=1, allow_inf_nan=False)
    parser_failure_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    block_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    citation_usefulness: float = Field(ge=0, le=1, allow_inf_nan=False)
    contradiction_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    status: Literal["healthy", "degraded", "unavailable"]


class SourceAcquisitionResult(ContractModel):
    plan: SourcePlan
    raw_receipts: list[RawDocumentReceipt] = Field(min_length=1)
    documents: list[NormalizedDocument] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    result_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EventCandidate(ContractModel):
    event_id: Annotated[str, Field(min_length=1)]
    entity_ids: list[str] = Field(min_length=1)
    detected_at: AwareDatetime
    event_type: Annotated[str, Field(min_length=1)]
    source_evidence_ids: list[str] = Field(min_length=1)
    novelty_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    urgency_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    requires_case: bool


class SourceTime(ContractModel):
    event_time: AwareDatetime | None = None
    published_at: AwareDatetime | None = None
    available_at: AwareDatetime
    retrieved_at: AwareDatetime
    revised_at: AwareDatetime | None = None


class FetchedDocument(ContractModel):
    source_id: Annotated[str, Field(min_length=1)]
    request_id: Annotated[str, Field(min_length=1)]
    url: Annotated[str, Field(min_length=1)]
    connector: Annotated[str, Field(min_length=1)]
    connector_version: Annotated[str, Field(min_length=1)]
    status_code: int = Field(ge=100, le=599)
    headers: dict[str, str] = Field(default_factory=dict)
    body: bytes = Field(min_length=1)
    fetched_at: AwareDatetime
    media_type: Annotated[str, Field(min_length=1)]


class RawDocumentReceipt(ContractModel):
    source_id: Annotated[str, Field(min_length=1)]
    request_id: Annotated[str, Field(min_length=1)]
    url: Annotated[str, Field(min_length=1)]
    connector: Annotated[str, Field(min_length=1)]
    connector_version: Annotated[str, Field(min_length=1)]
    status_code: int = Field(ge=100, le=599)
    headers: dict[str, str] = Field(default_factory=dict)
    fetched_at: AwareDatetime
    media_type: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    raw_uri: Annotated[str, Field(min_length=1)]
    byte_length: int = Field(gt=0)


class NormalizedDocument(ContractModel):
    document_id: Annotated[str, Field(min_length=1)]
    source_id: Annotated[str, Field(min_length=1)]
    source_url: Annotated[str, Field(min_length=1)]
    title: str | None = None
    text: Annotated[str, Field(min_length=1)]
    document_type: Annotated[str, Field(min_length=1)]
    entity_ids: list[str] = Field(default_factory=list)
    source_time: SourceTime
    raw_receipt: RawDocumentReceipt
    normalized_content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    injection_flags: list[str] = Field(default_factory=list)
    parser_version: Annotated[str, Field(min_length=1)]
    extraction_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
