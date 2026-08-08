"""Typed source-intelligence requests and manifests."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from ._base import ContractModel

SourceType = Literal[
    "official_api", "licensed_api", "official_web", "rss", "social", "community", "crawler"
]


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


class SourceRequest(ContractModel):
    case_id: Annotated[str, Field(min_length=1)]
    entity_ids: list[str] = Field(default_factory=list)
    information_type: Annotated[str, Field(min_length=1)]
    query: Annotated[str, Field(min_length=1)]
    as_of: AwareDatetime
    mode: Literal["replay", "historical", "live"]
    freshness: timedelta | None = None
    corroboration_required: bool = False
    max_sources: int = Field(gt=0)
    max_cost_usd: float = Field(ge=0, allow_inf_nan=False)


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


class EventCandidate(ContractModel):
    event_id: Annotated[str, Field(min_length=1)]
    entity_ids: list[str] = Field(min_length=1)
    detected_at: AwareDatetime
    event_type: Annotated[str, Field(min_length=1)]
    source_evidence_ids: list[str] = Field(min_length=1)
    novelty_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    urgency_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    requires_case: bool
