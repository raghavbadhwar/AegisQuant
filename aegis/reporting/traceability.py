"""Candidate-only, content-addressed (not authenticated) engineering traceability."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import PREDECLARED_STRATEGY_IDS, canonical_sha256
from aegis.contracts._base import CandidateContractModel

_SHA256 = r"^[0-9a-f]{64}$"


class ReleaseDisposition(StrEnum):
    """Non-authoritative disposition; no release-accepted value exists here."""

    ENGINEERING_ONLY = "engineering_only"
    RELEASE_GATED = "release_gated"


class SourceProvenanceReference(CandidateContractModel):
    """Immutable source/artifact receipt reference, without raw source content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=_SHA256)
    available_at: AwareDatetime


class SnapshotReference(CandidateContractModel):
    """Immutable point-in-time snapshot reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=_SHA256)
    as_of: AwareDatetime


class RunLedgerReceiptReference(CandidateContractModel):
    """Hash-only engineering replay receipt reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ledger_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    record_hash: str = Field(pattern=_SHA256)
    snapshot_hash: str = Field(pattern=_SHA256)
    as_of: AwareDatetime
    authority: Literal["engineering_only"] = "engineering_only"


class TraceabilityReceiptReference(CandidateContractModel):
    """Reference to a separately retained receipt that binds one original report seal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    report_content_hash: str = Field(pattern=_SHA256)
    recorded_at: AwareDatetime


class StrategyComparisonReadiness(CandidateContractModel):
    """Six-way comparison readiness, never a performance or promotion claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["not_ready", "engineering_only_complete"]
    comparison_spec_hash: str | None = Field(default=None, pattern=_SHA256)
    strategy_ids: tuple[str, ...] = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def references_exactly_the_predeclared_strategies(self) -> StrategyComparisonReadiness:
        if len(self.strategy_ids) != len(set(self.strategy_ids)) or set(self.strategy_ids) != set(
            PREDECLARED_STRATEGY_IDS
        ):
            raise ValueError(
                "strategy comparison readiness requires all six predeclared strategies"
            )
        if self.status == "not_ready" and self.comparison_spec_hash is not None:
            raise ValueError("not-ready strategy comparison cannot claim a comparison receipt")
        if self.status == "engineering_only_complete" and self.comparison_spec_hash is None:
            raise ValueError("completed strategy comparison requires a comparison receipt hash")
        return self


class EngineeringTraceabilityReport(CandidateContractModel):
    """Read-only candidate projection that cannot claim release eligibility."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str = Field(min_length=1)
    as_of: AwareDatetime
    source_provenance: tuple[SourceProvenanceReference, ...] = Field(min_length=1)
    snapshots: tuple[SnapshotReference, ...] = Field(min_length=1)
    run_ledger_receipts: tuple[RunLedgerReceiptReference, ...] = Field(min_length=1)
    strategy_comparison: StrategyComparisonReadiness
    release_disposition: ReleaseDisposition
    release_blockers: tuple[str, ...] = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"
    release_eligible: Literal[False] = False
    content_hash: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def binds_point_in_time_receipts_and_release_gate(self) -> EngineeringTraceabilityReport:
        source_ids = [reference.source_id for reference in self.source_provenance]
        snapshot_ids = [reference.snapshot_id for reference in self.snapshots]
        run_ids = [receipt.run_id for receipt in self.run_ledger_receipts]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("traceability source IDs must be unique")
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise ValueError("traceability snapshot IDs must be unique")
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("traceability run ledger receipt IDs must be unique")
        if any(reference.available_at > self.as_of for reference in self.source_provenance):
            raise ValueError(
                "traceability source provenance cannot be available after report cutoff"
            )
        if any(snapshot.as_of > self.as_of for snapshot in self.snapshots):
            raise ValueError("traceability snapshot cannot be after report cutoff")
        if any(receipt.as_of > self.as_of for receipt in self.run_ledger_receipts):
            raise ValueError("traceability run receipt cannot be after report cutoff")
        snapshot_hashes = {snapshot.content_hash for snapshot in self.snapshots}
        if any(
            receipt.snapshot_hash not in snapshot_hashes for receipt in self.run_ledger_receipts
        ):
            raise ValueError("traceability run receipt must reference a listed snapshot hash")
        if any(not blocker.strip() for blocker in self.release_blockers):
            raise ValueError("traceability release blockers must be non-empty")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("traceability report content hash mismatch")
        return self

    def sealed(self) -> EngineeringTraceabilityReport:
        """Return a deterministic content-addressed traceability projection."""
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = EngineeringTraceabilityReport.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})

    def verified(
        self, trusted_receipt: TraceabilityReceiptReference
    ) -> EngineeringTraceabilityReport:
        """Revalidate this report against a separately retained original seal receipt."""
        validated = EngineeringTraceabilityReport.model_validate(self.model_dump(mode="json"))
        receipt = TraceabilityReceiptReference.model_validate(
            trusted_receipt.model_dump(mode="json")
        )
        if validated.content_hash is None:
            raise ValueError("traceability report must be sealed")
        if receipt.report_id != validated.report_id:
            raise ValueError("traceability receipt does not match the report ID")
        if receipt.report_content_hash != validated.content_hash:
            raise ValueError("traceability report does not match the trusted receipt seal")
        return validated


def traceability_view(
    report: EngineeringTraceabilityReport,
    trusted_receipt: TraceabilityReceiptReference,
) -> dict[str, object]:
    """Render metadata only after matching an externally retained original seal receipt."""
    verified = report.verified(trusted_receipt)
    return {
        "report_id": verified.report_id,
        "as_of": verified.as_of,
        "authority": verified.authority,
        "release_disposition": verified.release_disposition.value,
        "release_eligible": verified.release_eligible,
        "source_count": len(verified.source_provenance),
        "snapshot_hashes": tuple(snapshot.content_hash for snapshot in verified.snapshots),
        "run_ledger_receipts": tuple(
            (receipt.run_id, receipt.record_hash) for receipt in verified.run_ledger_receipts
        ),
        "strategy_comparison_status": verified.strategy_comparison.status,
        "release_blockers": verified.release_blockers,
        "content_hash": verified.content_hash,
    }
