"""Pure, fixture-only evidence gate for deterministic forecasts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import field_validator, model_validator

from aegisquant.contracts.common import Identifier, Sha256Digest, StrictModel, require_utc
from aegisquant.contracts.evidence import EvidenceRecord, NumericClaim
from aegisquant.contracts.research import DataSnapshot
from aegisquant.quant.portfolio import Forecast
from aegisquant.security.digests import digest_canonical


class EvidenceDigestRef(StrictModel):
    schema_version: Literal[1] = 1
    evidence_id: UUID
    evidence_digest: Sha256Digest


class ForecastAssessmentOutcome(StrEnum):
    SUPPORTED = "SUPPORTED"
    ABSTAIN = "ABSTAIN"


def forecast_evidence_content_digest(
    *,
    forecast_digest: str,
    evidence_refs: tuple[EvidenceDigestRef, ...],
    numeric_claims: tuple[NumericClaim, ...],
    supporting_evidence_ids: tuple[UUID, ...],
    counter_evidence_ids: tuple[UUID, ...],
    resolved_counter_evidence_ids: tuple[UUID, ...],
) -> str:
    return digest_canonical(
        {
            "forecast_digest": forecast_digest,
            "evidence_refs": evidence_refs,
            "numeric_claims": numeric_claims,
            "supporting_evidence_ids": supporting_evidence_ids,
            "counter_evidence_ids": counter_evidence_ids,
            "resolved_counter_evidence_ids": resolved_counter_evidence_ids,
        }
    )


def forecast_evidence_manifest_digest(
    *,
    tenant_id: str,
    case_id: UUID,
    snapshot_id: str,
    content_digest: str,
    evaluation_cutoff: datetime,
) -> str:
    return digest_canonical(
        {
            "tenant_id": tenant_id,
            "case_id": case_id,
            "snapshot_id": snapshot_id,
            "content_digest": content_digest,
            "evaluation_cutoff": evaluation_cutoff,
        }
    )


class ForecastEvidenceBundle(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    snapshot_id: Identifier
    snapshot: DataSnapshot
    evaluation_cutoff: datetime
    forecast: Forecast
    forecast_digest: Sha256Digest
    evidence: tuple[EvidenceRecord, ...]
    evidence_refs: tuple[EvidenceDigestRef, ...]
    numeric_claims: tuple[NumericClaim, ...]
    supporting_evidence_ids: tuple[UUID, ...]
    counter_evidence_ids: tuple[UUID, ...] = ()
    resolved_counter_evidence_ids: tuple[UUID, ...] = ()

    @field_validator(
        "evidence",
        "evidence_refs",
        "numeric_claims",
        "supporting_evidence_ids",
        "counter_evidence_ids",
        "resolved_counter_evidence_ids",
        mode="before",
    )
    @classmethod
    def json_arrays_are_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("evaluation_cutoff", mode="before")
    @classmethod
    def cutoff_is_utc(cls, value: object) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise ValueError("evaluation_cutoff must be a UTC datetime")
        return require_utc(value)

    @model_validator(mode="after")
    def references_are_exact(self) -> ForecastEvidenceBundle:
        if (
            self.snapshot.tenant_id != self.tenant_id
            or any(item.tenant_id != self.tenant_id for item in self.evidence)
            or any(item.tenant_id != self.tenant_id for item in self.numeric_claims)
        ):
            raise ValueError("snapshot, evidence, and claims must belong to the bundle tenant")
        if self.snapshot.case_id != self.case_id:
            raise ValueError("snapshot must belong to the bundle case")
        if self.snapshot.snapshot_id != self.snapshot_id:
            raise ValueError("snapshot_id must bind the frozen snapshot")
        if self.snapshot.as_of != self.evaluation_cutoff:
            raise ValueError("evaluation_cutoff must bind the snapshot as_of time")
        if digest_canonical(self.forecast) != self.forecast_digest:
            raise ValueError("forecast_digest does not bind the forecast")

        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        refs_by_id = {item.evidence_id: item for item in self.evidence_refs}
        if len(evidence_by_id) != len(self.evidence) or len(refs_by_id) != len(self.evidence_refs):
            raise ValueError("evidence IDs and digest references must be unique")
        if evidence_by_id.keys() != refs_by_id.keys():
            raise ValueError("evidence_refs must bind every evidence record exactly")
        if any(
            refs_by_id[evidence_id].evidence_digest != digest_canonical(record)
            for evidence_id, record in evidence_by_id.items()
        ):
            raise ValueError("evidence_digest does not bind its evidence record")
        content_digest = forecast_evidence_content_digest(
            forecast_digest=self.forecast_digest,
            evidence_refs=self.evidence_refs,
            numeric_claims=self.numeric_claims,
            supporting_evidence_ids=self.supporting_evidence_ids,
            counter_evidence_ids=self.counter_evidence_ids,
            resolved_counter_evidence_ids=self.resolved_counter_evidence_ids,
        )
        if self.snapshot.content_digest != content_digest:
            raise ValueError("snapshot content_digest does not bind the forecast evidence bundle")
        if self.snapshot.manifest_digest != forecast_evidence_manifest_digest(
            tenant_id=self.tenant_id,
            case_id=self.case_id,
            snapshot_id=self.snapshot_id,
            content_digest=content_digest,
            evaluation_cutoff=self.evaluation_cutoff,
        ):
            raise ValueError("snapshot manifest_digest does not bind the frozen snapshot")

        support = set(self.supporting_evidence_ids)
        counter = set(self.counter_evidence_ids)
        resolved = set(self.resolved_counter_evidence_ids)
        if not support | counter <= evidence_by_id.keys():
            raise ValueError("support and counter-evidence IDs must reference bundled evidence")
        if support & counter:
            raise ValueError("evidence cannot be both supporting and counter-evidence")
        if not resolved <= counter:
            raise ValueError("resolved counter-evidence IDs must reference counter-evidence")
        return self


class ForecastAssessment(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    snapshot_id: Identifier
    evaluated_at: datetime
    outcome: ForecastAssessmentOutcome
    bundle_digest: Sha256Digest
    forecast_digest: Sha256Digest
    supporting_evidence_digests: tuple[Sha256Digest, ...]
    reason_codes: tuple[Identifier, ...]

    @field_validator("supporting_evidence_digests", "reason_codes", mode="before")
    @classmethod
    def json_arrays_are_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_is_utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def outcome_matches_reasons(self) -> ForecastAssessment:
        if (self.outcome is ForecastAssessmentOutcome.SUPPORTED) != (not self.reason_codes):
            raise ValueError("SUPPORTED requires no reason codes; ABSTAIN requires at least one")
        return self


def assess_forecast_evidence(
    bundle: ForecastEvidenceBundle, *, as_of: datetime
) -> ForecastAssessment:
    """Assess fixed evidence with explicit, non-learned minimum support rules."""

    as_of = require_utc(as_of)
    if as_of != bundle.evaluation_cutoff:
        raise ValueError("as_of must equal the bundle evaluation cutoff")

    evidence_by_id = {item.evidence_id: item for item in bundle.evidence}
    support_ids = set(bundle.supporting_evidence_ids)
    supporting = tuple(evidence_by_id[item] for item in sorted(support_ids, key=str))
    claim_evidence_ids = {item.evidence_id for item in bundle.numeric_claims}
    expected_claims = {
        "forecast-expected-return": bundle.forecast.expected_return,
        "forecast-probability-positive": bundle.forecast.probability_positive,
        "forecast-confidence": bundle.forecast.confidence,
        "forecast-uncertainty": bundle.forecast.uncertainty,
    }
    actual_claims = {item.name: item for item in bundle.numeric_claims}
    reasons: list[str] = []
    if len(support_ids) < 2:
        reasons.append("INSUFFICIENT_SUPPORT")
    if len({item.source_type for item in supporting}) < 2:
        reasons.append("INDEPENDENT_SOURCES_REQUIRED")
    if (
        len({item.raw_content_digest for item in supporting}) < 2
        or len(
            {
                urlparse(item.source_url).netloc.lower()
                for item in supporting
                if item.source_url is not None
            }
        )
        < 2
    ):
        reasons.append("INDEPENDENT_AUTHORITIES_REQUIRED")
    if any(bundle.forecast.instrument_id not in item.entity_ids for item in supporting):
        reasons.append("IRRELEVANT_SUPPORT")
    if (
        claim_evidence_ids - support_ids
        or support_ids - claim_evidence_ids
        or len(actual_claims) != len(bundle.numeric_claims)
        or actual_claims.keys() != expected_claims.keys()
        or any(
            actual_claims[name].value != value or actual_claims[name].unit != "ratio"
            for name, value in expected_claims.items()
        )
    ):
        reasons.append("UNBOUND_FORECAST_CLAIMS")
    if any(not item.historical_safe for item in bundle.evidence):
        reasons.append("UNSAFE_HISTORICAL_EVIDENCE")
    if any(item.available_at >= as_of for item in bundle.evidence):
        reasons.append("EVIDENCE_NOT_BEFORE_CUTOFF")
    if set(bundle.counter_evidence_ids) - set(bundle.resolved_counter_evidence_ids):
        reasons.append("UNRESOLVED_COUNTER_EVIDENCE")

    return ForecastAssessment(
        tenant_id=bundle.tenant_id,
        case_id=bundle.case_id,
        snapshot_id=bundle.snapshot_id,
        evaluated_at=as_of,
        outcome=(
            ForecastAssessmentOutcome.ABSTAIN if reasons else ForecastAssessmentOutcome.SUPPORTED
        ),
        bundle_digest=digest_canonical(bundle),
        forecast_digest=bundle.forecast_digest,
        supporting_evidence_digests=tuple(digest_canonical(item) for item in supporting),
        reason_codes=tuple(reasons),
    )
