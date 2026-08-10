from datetime import UTC, datetime, timedelta

import pytest

import aegis.reporting as reporting
from aegis.reporting.traceability import (
    EngineeringTraceabilityReport,
    ReleaseDisposition,
    RunLedgerReceiptReference,
    SnapshotReference,
    SourceProvenanceReference,
    StrategyComparisonReadiness,
    TraceabilityReceiptReference,
    traceability_view,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64
RELEASE_BLOCKER = (
    "No approved survivorship-safe PIT market/universe/corporate-action/delisting source exists."
)


def report() -> EngineeringTraceabilityReport:
    return EngineeringTraceabilityReport(
        report_id="engineering-traceability-20260810",
        as_of=NOW,
        source_provenance=(
            SourceProvenanceReference(
                source_id="yahoo-engineering-v3",
                artifact_id="yahoo-engineering-2019-2025",
                content_hash=HASH_A,
                available_at=NOW,
            ),
        ),
        snapshots=(
            SnapshotReference(
                snapshot_id="yahoo-engineering-snapshot-2025-12-31",
                content_hash=HASH_B,
                as_of=NOW,
            ),
        ),
        run_ledger_receipts=(
            RunLedgerReceiptReference(
                ledger_id="aegisquant-yahoo-engineering-2019-2025",
                run_id="engineering-replay-20260810",
                record_hash=HASH_C,
                snapshot_hash=HASH_B,
                as_of=NOW,
            ),
        ),
        strategy_comparison=StrategyComparisonReadiness(
            status="not_ready",
            comparison_spec_hash=None,
            strategy_ids=(
                "equal-weight-v1",
                "inverse-vol-v1",
                "simple-factor-v1",
                "fundamental-only-v1",
                "quant-only-v1",
                "combined-multistrategy-v1",
            ),
            reason="Engineering fixture cannot support release-grade qualification.",
        ),
        release_disposition=ReleaseDisposition.RELEASE_GATED,
        release_blockers=(RELEASE_BLOCKER,),
    )


def receipt_for(sealed: EngineeringTraceabilityReport) -> TraceabilityReceiptReference:
    assert sealed.content_hash is not None
    return TraceabilityReceiptReference(
        receipt_id="governed-receipt-20260810",
        report_id=sealed.report_id,
        report_content_hash=sealed.content_hash,
        recorded_at=NOW,
    )


def test_traceability_projection_is_sealed_candidate_only_and_release_gated() -> None:
    sealed = report().sealed()

    view = traceability_view(sealed, receipt_for(sealed))

    assert sealed.content_hash
    assert view == {
        "report_id": "engineering-traceability-20260810",
        "as_of": NOW,
        "authority": "candidate_only",
        "release_disposition": "release_gated",
        "release_eligible": False,
        "source_count": 1,
        "snapshot_hashes": (HASH_B,),
        "run_ledger_receipts": (("engineering-replay-20260810", HASH_C),),
        "strategy_comparison_status": "not_ready",
        "release_blockers": (RELEASE_BLOCKER,),
        "content_hash": sealed.content_hash,
    }


def test_traceability_projection_revalidates_model_copy_tampering() -> None:
    sealed = report().sealed()
    future_source = sealed.source_provenance[0].model_copy(
        update={"available_at": NOW + timedelta(seconds=1)}
    )

    with pytest.raises(ValueError, match="source provenance cannot be available"):
        sealed.model_copy(update={"source_provenance": (future_source,)})


def test_traceability_view_requires_an_externally_retained_original_seal() -> None:
    original = report().sealed()
    original_receipt = receipt_for(original)
    revised = (
        report()
        .model_copy(update={"release_blockers": ("Forged but validator-valid replacement.",)})
        .sealed()
    )

    with pytest.raises(ValueError, match="does not match the trusted receipt"):
        traceability_view(revised, original_receipt)


def test_reporting_exports_the_candidate_traceability_projection() -> None:
    assert reporting.EngineeringTraceabilityReport
    assert reporting.ReleaseDisposition
    assert reporting.TraceabilityReceiptReference
    assert reporting.traceability_view
