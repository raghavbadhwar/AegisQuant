"""Read-only validation and rendering boundary for adaptive research artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import model_validator

from .adaptation import AdaptiveHistory, _SealedAdaptiveModel, evaluate_registered_adaptive_fixture
from .adaptive_evidence import AdaptiveEvidenceCheckpoint, AdaptiveEvidenceIndex


class AdaptiveReport(_SealedAdaptiveModel):
    """Candidate-only report; it is valid only with a verified local index context."""

    report_id: str
    history: AdaptiveHistory
    evidence_checkpoint: AdaptiveEvidenceCheckpoint

    @model_validator(mode="after")
    def binds_history_to_one_cutoff(self) -> AdaptiveReport:
        history = AdaptiveHistory.model_validate(self.history.model_dump(mode="json"))
        checkpoint = AdaptiveEvidenceCheckpoint.model_validate(
            self.evidence_checkpoint.model_dump(mode="json")
        )
        if history.content_hash is None or checkpoint.content_hash is None:
            raise ValueError("adaptive report requires sealed history and evidence checkpoint")
        if history.policy.as_of != checkpoint.as_of:
            raise ValueError(
                "adaptive report cutoff must match its history and evidence checkpoint"
            )
        return self


def load_validated_adaptive_report(
    report_path: str | Path, *, index_path: str | Path
) -> AdaptiveReport:
    """Load a report only after rebuilding its required local evidence and evaluator context."""

    report = AdaptiveReport.model_validate_json(Path(report_path).read_bytes())
    if report.content_hash is None:
        raise ValueError("adaptive report must be sealed")
    index = AdaptiveEvidenceIndex(index_path, read_only=True)
    checkpoint = index.checkpoint(report.evidence_checkpoint.as_of)
    if checkpoint.model_dump(mode="json") != report.evidence_checkpoint.model_dump(mode="json"):
        raise ValueError("adaptive report evidence index is stale or substituted")
    for entry in report.history.entries:
        recommendation_checkpoint = index.checkpoint(entry.recommendation.as_of)
        proposal_checkpoint = index.checkpoint(entry.recommendation.result.manifest.proposal.as_of)
        if recommendation_checkpoint.model_dump(
            mode="json"
        ) != entry.recommendation.evidence_checkpoint.model_dump(
            mode="json"
        ) or proposal_checkpoint.model_dump(
            mode="json"
        ) != entry.recommendation.result.manifest.proposal.evidence_checkpoint.model_dump(
            mode="json"
        ):
            raise ValueError("adaptive report nested evidence index is stale or substituted")
        expected = evaluate_registered_adaptive_fixture(entry.recommendation.result.manifest)
        if expected.model_dump(mode="json") != entry.recommendation.result.model_dump(mode="json"):
            raise ValueError(
                "adaptive report registered evaluator result is unavailable or mismatched"
            )
    return report


def adaptive_report_view(report: AdaptiveReport) -> dict[str, Any]:
    """Return a deterministic, action-free public view after validated loading."""

    return {
        "status": {
            "authority": "candidate_only",
            "evidence_status": "engineering_only",
            "release_status": "release_gated",
            "limitations": "no approval, promotion, deployment, portfolio, or order authority",
        },
        "report_id": report.report_id,
        "as_of": report.evidence_checkpoint.as_of.isoformat(),
        "history_hash": report.history.content_hash,
        "evidence_checkpoint_hash": report.evidence_checkpoint.content_hash,
        "stop_reason": report.history.stop_reason,
        "recommendations": [
            {
                "recommendation_id": entry.recommendation.recommendation_id,
                "disposition": entry.recommendation.disposition,
                "reason": entry.recommendation.reason,
                "content_hash": entry.recommendation.content_hash,
            }
            for entry in report.history.entries
        ],
    }
