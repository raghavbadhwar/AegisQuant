"""Human-authorized promotion validation; no mutation is performed here."""

from __future__ import annotations

from pathlib import Path

from aegis.contracts import (
    CandidatePatchMetadata,
    HoldoutUnlock,
    LearningCandidate,
    PromotionDecision,
    ShadowResult,
    ValidationReport,
    canonical_sha256,
)

from .boundaries import validate_candidate_target


class PromotionDenied(RuntimeError):
    pass


_REQUIRED_STAGES = {
    "preflight",
    "replay",
    "historical_dev",
    "holdback",
    "purged_cv",
    "overfitting",
    "cost_stress",
    "shadow",
}


def authorize_promotion(
    candidate: LearningCandidate,
    report: ValidationReport,
    decision: PromotionDecision,
    *,
    patch: CandidatePatchMetadata,
    holdout_unlock: HoldoutUnlock,
    shadow_result: ShadowResult,
    project_root: Path,
) -> bool:
    """Validate every immutable binding; never apply a patch or mutate production."""
    candidate_hash = canonical_sha256(candidate)
    if candidate.status != "shadow":
        raise PromotionDenied("candidate must complete shadow status before promotion")
    validate_candidate_target(project_root, patch.target_path)
    if patch.candidate_id != candidate.candidate_id or patch.patch_hash != canonical_sha256(
        candidate.proposed_patch
    ):
        raise PromotionDenied("candidate patch metadata is not bound to the candidate")
    if report.candidate_id != candidate.candidate_id or report.candidate_hash != candidate_hash:
        raise PromotionDenied("validation report is not bound to the candidate")
    if report.evaluator_id == candidate.proposer_id:
        raise PromotionDenied("candidate proposer cannot evaluate its own candidate")
    if not report.passed or not _REQUIRED_STAGES.issubset(
        {stage for stage in report.stages if report.stage_passes.get(stage) is True}
    ):
        raise PromotionDenied("all required validation stages must pass")
    if (
        holdout_unlock.unlock_id != report.holdout_unlock_id
        or holdout_unlock.suite_id != candidate.evaluation_suite_id
        or holdout_unlock.unlocked_at > report.evaluated_at
    ):
        raise PromotionDenied("holdout unlock is not bound to the evaluation")
    if holdout_unlock.human_approver_id in {
        candidate.proposer_id,
        report.evaluator_id,
    }:
        raise PromotionDenied("holdout approver must be independent")
    if (
        shadow_result.candidate_id != candidate.candidate_id
        or not shadow_result.passed
        or shadow_result.completed_at > report.evaluated_at
    ):
        raise PromotionDenied("passing shadow result is not bound to the evaluation")
    if (
        decision.candidate_id != candidate.candidate_id
        or decision.candidate_hash != candidate_hash
        or decision.validation_report_id != report.report_id
        or decision.validation_report_hash != report.content_hash
        or decision.patch_metadata_hash != canonical_sha256(patch)
        or decision.holdout_unlock_id != holdout_unlock.unlock_id
        or decision.holdout_unlock_hash != holdout_unlock.content_hash
        or decision.shadow_result_id != shadow_result.shadow_id
        or decision.shadow_result_hash != shadow_result.content_hash
        or decision.evaluator_id != report.evaluator_id
    ):
        raise PromotionDenied("promotion decision hash bindings do not match")
    if decision.decided_at <= report.evaluated_at:
        raise PromotionDenied("promotion decision must follow completed evaluation")
    if decision.human_approver_id in {candidate.proposer_id, report.evaluator_id}:
        raise PromotionDenied("promotion approver must be independent of proposer and evaluator")
    return decision.decision == "promote"
