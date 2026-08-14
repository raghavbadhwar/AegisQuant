"""Horizon gates and manual approval binding for learning candidates."""

from datetime import datetime

from aegisquant.contracts.common import require_utc
from aegisquant.contracts.learning import LearningCandidate, LearningEvaluation, PromotionApproval


def evaluate_candidate(
    candidate: LearningCandidate,
    *,
    evaluator_id: str,
    evaluation_manifest_digest: str,
    shadow_passed: bool,
    canary_passed: bool,
    now: datetime,
) -> LearningEvaluation:
    evaluated_at = require_utc(now)
    if evaluated_at < candidate.matures_at:
        raise ValueError("candidate outcome has not reached its declared horizon")
    return LearningEvaluation(
        tenant_id=candidate.tenant_id,
        case_id=candidate.case_id,
        candidate_id=candidate.candidate_id,
        evaluation_manifest_digest=evaluation_manifest_digest,
        evaluator_id=evaluator_id,
        shadow_passed=shadow_passed,
        canary_passed=canary_passed,
        evaluated_at=evaluated_at,
    )


def approve_candidate(
    candidate: LearningCandidate,
    evaluation: LearningEvaluation,
    *,
    approver_id: str,
    approval_digest: str,
    rollback_manifest_digest: str,
    now: datetime,
) -> PromotionApproval:
    approved_at = require_utc(now)
    if (
        evaluation.tenant_id != candidate.tenant_id
        or evaluation.case_id != candidate.case_id
        or evaluation.candidate_id != candidate.candidate_id
    ):
        raise ValueError("approval evaluation is outside candidate tenant/case scope")
    if approved_at < candidate.matures_at:
        raise ValueError("candidate cannot be approved before maturity")
    if approved_at < evaluation.evaluated_at:
        raise ValueError("approval cannot precede evaluation")
    if not evaluation.shadow_passed or not evaluation.canary_passed:
        raise ValueError("candidate requires successful independent shadow and canary evaluation")
    return PromotionApproval(
        tenant_id=candidate.tenant_id,
        case_id=candidate.case_id,
        candidate_id=candidate.candidate_id,
        evaluation_manifest_digest=evaluation.evaluation_manifest_digest,
        approver_id=approver_id,
        approval_digest=approval_digest,
        rollback_manifest_digest=rollback_manifest_digest,
        approved_at=approved_at,
    )
