from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from aegisquant.contracts.evidence import EvidenceRecord, NumericClaim
from aegisquant.contracts.research import DataSnapshot
from aegisquant.intelligence.forecast_evidence import (
    EvidenceDigestRef,
    ForecastAssessmentOutcome,
    ForecastEvidenceBundle,
    assess_forecast_evidence,
    forecast_evidence_content_digest,
    forecast_evidence_manifest_digest,
)
from aegisquant.quant.portfolio import Forecast
from aegisquant.security.digests import digest_canonical

CASE_ID = UUID("00000000-0000-0000-0000-000000000201")
CUTOFF = datetime(2026, 1, 10, tzinfo=UTC)
FIXTURE = Path("data/fixtures/research/forecast_evidence_control.json")


def evidence(
    number: int,
    *,
    source_type: str,
    available_at: datetime | None = None,
) -> EvidenceRecord:
    observed = CUTOFF - timedelta(days=2)
    return EvidenceRecord(
        tenant_id="tenant-fixture",
        evidence_id=UUID(f"00000000-0000-0000-0000-{number:012d}"),
        source_type=source_type,
        source_url=f"fixture://{source_type}/source-{number}",
        entity_ids=("AAA",),
        document_type="recorded-fixture",
        event_time=observed,
        published_at=observed,
        first_observed_at=observed,
        available_at=available_at or CUTOFF - timedelta(days=1),
        ingested_at=observed,
        raw_object_uri=f"fixture://objects/evidence-{number}",
        raw_content_digest="sha256:" + f"{number:x}" * 64,
        capture_metadata_digest="sha256:" + f"{number + 2:x}" * 64,
        extractor_version="fixture-extractor-v1",
        parser_version="fixture-parser-v1",
        rights_manifest_id="fixture-rights-v1",
        source_quality="0.90",
        extraction_confidence="0.95",
        historical_safe=True,
    )


def bundle(
    *,
    records: tuple[EvidenceRecord, ...] | None = None,
    supporting_ids: tuple[UUID, ...] | None = None,
    counter_ids: tuple[UUID, ...] = (),
    claims: tuple[NumericClaim, ...] | None = None,
) -> ForecastEvidenceBundle:
    records = records or (
        evidence(1, source_type="filing"),
        evidence(2, source_type="exchange-release"),
    )
    supporting_ids = supporting_ids or tuple(item.evidence_id for item in records)
    forecast = Forecast(
        instrument_id="AAA",
        horizon_days=20,
        expected_return="0.08",
        probability_positive="0.65",
        confidence="0.75",
        uncertainty="0.20",
        feature_provenance=("recorded-evidence-v1",),
    )
    claims = claims or tuple(
        NumericClaim(
            tenant_id="tenant-fixture",
            claim_id=UUID(f"00000000-0000-0000-0001-{index:012d}"),
            name=name,
            value=value,
            unit="ratio",
            evidence_id=records[(index - 1) % len(records)].evidence_id,
            source_coordinate=f"fixture-row-{index}",
        )
        for index, (name, value) in enumerate(
            (
                ("forecast-expected-return", forecast.expected_return),
                ("forecast-probability-positive", forecast.probability_positive),
                ("forecast-confidence", forecast.confidence),
                ("forecast-uncertainty", forecast.uncertainty),
            ),
            start=1,
        )
    )
    evidence_refs = tuple(
        EvidenceDigestRef(
            evidence_id=item.evidence_id,
            evidence_digest=digest_canonical(item),
        )
        for item in records
    )
    content_digest = forecast_evidence_content_digest(
        forecast_digest=digest_canonical(forecast),
        evidence_refs=evidence_refs,
        numeric_claims=claims,
        supporting_evidence_ids=supporting_ids,
        counter_evidence_ids=counter_ids,
        resolved_counter_evidence_ids=(),
    )
    snapshot = DataSnapshot(
        tenant_id="tenant-fixture",
        case_id=CASE_ID,
        snapshot_id="forecast-control-v1",
        manifest_digest=forecast_evidence_manifest_digest(
            tenant_id="tenant-fixture",
            case_id=CASE_ID,
            snapshot_id="forecast-control-v1",
            content_digest=content_digest,
            evaluation_cutoff=CUTOFF,
        ),
        content_digest=content_digest,
        as_of=CUTOFF,
        frozen_at=CUTOFF,
    )
    return ForecastEvidenceBundle(
        tenant_id="tenant-fixture",
        case_id=CASE_ID,
        snapshot_id=snapshot.snapshot_id,
        snapshot=snapshot,
        evaluation_cutoff=CUTOFF,
        forecast=forecast,
        forecast_digest=digest_canonical(forecast),
        evidence=records,
        evidence_refs=evidence_refs,
        numeric_claims=claims,
        supporting_evidence_ids=supporting_ids,
        counter_evidence_ids=counter_ids,
        resolved_counter_evidence_ids=(),
    )


def test_two_independent_bound_sources_support_the_forecast() -> None:
    value = bundle()
    assessment = assess_forecast_evidence(value, as_of=CUTOFF)

    assert assessment.outcome is ForecastAssessmentOutcome.SUPPORTED
    assert assessment.forecast_digest == value.forecast_digest
    assert assessment.bundle_digest == digest_canonical(value)
    assert assessment.reason_codes == ()


@pytest.mark.parametrize(
    "value,reason",
    [
        (
            lambda: bundle(supporting_ids=(evidence(1, source_type="filing").evidence_id,)),
            "support",
        ),
        (
            lambda: bundle(
                records=(
                    evidence(1, source_type="filing"),
                    evidence(2, source_type="filing"),
                )
            ),
            "independent",
        ),
        (
            lambda: bundle(
                records=(
                    evidence(1, source_type="filing"),
                    evidence(2, source_type="exchange-release").model_copy(
                        update={
                            "raw_content_digest": evidence(
                                1, source_type="filing"
                            ).raw_content_digest
                        }
                    ),
                )
            ),
            "independent",
        ),
        (
            lambda: bundle(
                claims=(
                    NumericClaim(
                        tenant_id="tenant-fixture",
                        claim_id=UUID("00000000-0000-0000-0001-000000000001"),
                        name="forecast-expected-return",
                        value="101",
                        unit="ratio",
                        evidence_id=evidence(1, source_type="filing").evidence_id,
                        source_coordinate="fixture-row-1",
                    ),
                )
            ),
            "claim",
        ),
        (
            lambda: bundle(
                records=(
                    evidence(1, source_type="filing"),
                    evidence(2, source_type="exchange-release"),
                    evidence(3, source_type="analyst-note"),
                ),
                supporting_ids=(
                    evidence(1, source_type="filing").evidence_id,
                    evidence(2, source_type="exchange-release").evidence_id,
                ),
                counter_ids=(evidence(3, source_type="analyst-note").evidence_id,),
            ),
            "counter",
        ),
        (
            lambda: bundle(
                records=(
                    evidence(1, source_type="filing", available_at=CUTOFF),
                    evidence(2, source_type="exchange-release"),
                )
            ),
            "cutoff",
        ),
    ],
)
def test_missing_support_condition_abstains(
    value: Callable[[], ForecastEvidenceBundle], reason: str
) -> None:
    assessment = assess_forecast_evidence(value(), as_of=CUTOFF)
    assert assessment.outcome is ForecastAssessmentOutcome.ABSTAIN
    assert any(reason in item.lower() for item in assessment.reason_codes)


def test_tenant_snapshot_and_digest_mismatches_raise() -> None:
    value = bundle()
    raw = value.model_dump(mode="python")

    with pytest.raises(ValidationError, match="tenant"):
        ForecastEvidenceBundle.model_validate(
            raw | {"snapshot": value.snapshot.model_copy(update={"tenant_id": "tenant-other"})}
        )
    with pytest.raises(ValidationError, match="case"):
        ForecastEvidenceBundle.model_validate(
            raw
            | {
                "snapshot": value.snapshot.model_copy(
                    update={"case_id": UUID("00000000-0000-0000-0000-000000000999")}
                )
            }
        )
    with pytest.raises(ValidationError, match="snapshot"):
        ForecastEvidenceBundle.model_validate(raw | {"snapshot_id": "different-snapshot"})
    with pytest.raises(ValidationError, match="content_digest"):
        ForecastEvidenceBundle.model_validate(
            raw
            | {
                "snapshot": value.snapshot.model_copy(
                    update={"content_digest": "sha256:" + "f" * 64}
                )
            }
        )
    with pytest.raises(ValidationError, match="manifest_digest"):
        ForecastEvidenceBundle.model_validate(
            raw
            | {
                "snapshot": value.snapshot.model_copy(
                    update={"manifest_digest": "sha256:" + "f" * 64}
                )
            }
        )
    with pytest.raises(ValidationError, match="forecast_digest"):
        ForecastEvidenceBundle.model_validate(raw | {"forecast_digest": "sha256:" + "f" * 64})
    with pytest.raises(ValidationError, match="evidence_digest"):
        ForecastEvidenceBundle.model_validate(
            raw
            | {
                "evidence_refs": (
                    value.evidence_refs[0].model_copy(
                        update={"evidence_digest": "sha256:" + "f" * 64}
                    ),
                    value.evidence_refs[1],
                )
            }
        )
    with pytest.raises(ValueError, match="evaluation cutoff"):
        assess_forecast_evidence(value, as_of=CUTOFF + timedelta(seconds=1))


def test_recorded_control_fixture_is_supported() -> None:
    value = ForecastEvidenceBundle.model_validate_json(FIXTURE.read_bytes())
    assert assess_forecast_evidence(value, as_of=value.evaluation_cutoff).outcome is (
        ForecastAssessmentOutcome.SUPPORTED
    )
