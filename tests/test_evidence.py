from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from aegisquant.contracts.evidence import EvidenceRecord

D = "sha256:" + "a" * 64


def make_evidence(available_at: datetime) -> EvidenceRecord:
    return EvidenceRecord(
        tenant_id="tenant-a",
        evidence_id=uuid4(),
        source_type="official_filing",
        entity_ids=("entity-1",),
        document_type="10-Q",
        first_observed_at=available_at,
        available_at=available_at,
        ingested_at=available_at + timedelta(seconds=1),
        raw_object_uri="s3://evidence/sha256/a",
        raw_content_digest=D,
        capture_metadata_digest=D,
        extractor_version="extractor-1",
        parser_version="parser-1",
        rights_manifest_id="rights-1",
        source_quality="0.9",
        extraction_confidence="0.8",
        historical_safe=True,
    )


def test_point_in_time_eligibility_is_inclusive_at_available_time() -> None:
    available = datetime(2026, 1, 2, tzinfo=UTC)
    item = make_evidence(available)
    assert not item.eligible_as_of(available - timedelta(microseconds=1))
    assert item.eligible_as_of(available)


def test_available_at_cannot_precede_trusted_observation() -> None:
    available = datetime(2026, 1, 2, tzinfo=UTC)
    data = make_evidence(available).model_dump(mode="python")
    data["first_observed_at"] = available + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="available_at cannot precede"):
        EvidenceRecord.model_validate(data)
