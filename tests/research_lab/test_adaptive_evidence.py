from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aegis.contracts import canonical_sha256
from aegis.research_lab.adaptive_evidence import AdaptiveEvidenceIndex, AdaptiveEvidenceRecord


def test_evidence_index_appends_one_receipt_bound_record(tmp_path) -> None:
    observed_at = datetime(2026, 1, 15, tzinfo=UTC)
    payload = {"negative_result_id": "negative-1", "reason": "fixture_refuted"}
    record = AdaptiveEvidenceRecord(
        evidence_id="negative-1",
        record_kind="negative_result",
        payload=payload,
        payload_content_hash=canonical_sha256(payload),
        receipt_id="receipt-1",
        receipt_payload={"receipt_id": "receipt-1", "observed_at": observed_at.isoformat()},
        receipt_content_hash=canonical_sha256(
            {"receipt_id": "receipt-1", "observed_at": observed_at.isoformat()}
        ),
        observed_at=observed_at,
    ).sealed()

    index = AdaptiveEvidenceIndex(tmp_path / "adaptive-evidence.sqlite")

    checkpoint = index.append(record)

    assert checkpoint.record_ids == ("negative-1",)
    assert checkpoint.record_hashes == (record.content_hash,)
    assert checkpoint.content_hash is not None


def test_evidence_index_resolves_eligible_kinds_in_stable_id_order(tmp_path) -> None:
    observed_at = datetime(2026, 1, 15, tzinfo=UTC)
    index = AdaptiveEvidenceIndex(tmp_path / "adaptive-evidence.sqlite")
    for evidence_id, record_kind in (
        ("verification-1", "verification"),
        ("negative-2", "negative_result"),
        ("negative-1", "negative_result"),
    ):
        payload = {"evidence_id": evidence_id}
        index.append(
            AdaptiveEvidenceRecord(
                evidence_id=evidence_id,
                record_kind=record_kind,
                payload=payload,
                payload_content_hash=canonical_sha256(payload),
                receipt_id=f"receipt-{evidence_id}",
                receipt_payload={
                    "receipt_id": f"receipt-{evidence_id}",
                    "observed_at": observed_at.isoformat(),
                },
                receipt_content_hash=canonical_sha256(
                    {
                        "receipt_id": f"receipt-{evidence_id}",
                        "observed_at": observed_at.isoformat(),
                    }
                ),
                observed_at=observed_at,
            ).sealed()
        )

    resolved = index.resolve(
        as_of=observed_at,
        record_kinds=("negative_result", "refutation"),
    )

    assert tuple(record.evidence_id for record in resolved) == ("negative-1", "negative-2")


def test_evidence_record_binds_exact_receipt_payload() -> None:
    observed_at = datetime(2026, 1, 15, tzinfo=UTC)
    payload = {"negative_result_id": "negative-1"}
    receipt_payload = {"receipt_id": "receipt-1", "observed_at": observed_at.isoformat()}

    record = AdaptiveEvidenceRecord(
        evidence_id="negative-1",
        record_kind="negative_result",
        payload=payload,
        payload_content_hash=canonical_sha256(payload),
        receipt_id="receipt-1",
        receipt_payload=receipt_payload,
        receipt_content_hash=canonical_sha256(receipt_payload),
        observed_at=observed_at,
    ).sealed()

    assert record.content_hash is not None
    with pytest.raises(ValidationError, match="receipt content hash mismatch"):
        AdaptiveEvidenceRecord(
            evidence_id="negative-1",
            record_kind="negative_result",
            payload=payload,
            payload_content_hash=canonical_sha256(payload),
            receipt_id="receipt-1",
            receipt_payload=receipt_payload,
            receipt_content_hash="b" * 64,
            observed_at=observed_at,
        )


def test_evidence_record_requires_receipt_observed_time_to_match_index_time() -> None:
    observed_at = datetime(2026, 1, 15, tzinfo=UTC)
    payload = {"negative_result_id": "negative-1"}
    receipt_payload = {"receipt_id": "receipt-1", "observed_at": "2026-01-16T00:00:00+00:00"}

    with pytest.raises(ValidationError, match="receipt observed time mismatch"):
        AdaptiveEvidenceRecord(
            evidence_id="negative-1",
            record_kind="negative_result",
            payload=payload,
            payload_content_hash=canonical_sha256(payload),
            receipt_id="receipt-1",
            receipt_payload=receipt_payload,
            receipt_content_hash=canonical_sha256(receipt_payload),
            observed_at=observed_at,
        )
