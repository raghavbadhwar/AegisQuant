"""Horizon gates and manual approval binding for learning candidates."""

from datetime import datetime

from aegisquant.contracts.common import require_utc
from aegisquant.contracts.learning import (
    LearningCandidate,
    LearningEvaluation,
    LearningEvaluationV2,
    LearningProposalManifest,
    PromotionApproval,
    PromotionApprovalV2,
)
from aegisquant.security.digests import digest_canonical


def strategy_proposal_digest(proposal: LearningProposalManifest) -> str:
    return digest_canonical(
        {
            "strategy_parameter": proposal.strategy_parameter,
            "proposed_value": proposal.proposed_value,
        }
    )


def promotion_approval_digest(
    proposal: LearningProposalManifest, evaluation: LearningEvaluationV2
) -> str:
    return digest_canonical(
        {
            "proposal_manifest_digest": digest_canonical(proposal),
            "proposal_digest": proposal.proposal_digest,
            "evaluation_digest": digest_canonical(evaluation),
            "rollback_manifest_digest": proposal.rollback_manifest_digest,
        }
    )


def verify_candidate_proposal(
    candidate: LearningCandidate, proposal: LearningProposalManifest
) -> None:
    if (
        candidate.tenant_id != proposal.tenant_id
        or candidate.case_id != proposal.case_id
        or candidate.candidate_id != proposal.candidate_id
        or candidate.candidate_type != proposal.candidate_type
        or candidate.source_manifest_digest != digest_canonical(proposal)
        or proposal.proposal_digest != strategy_proposal_digest(proposal)
    ):
        raise ValueError("learning proposal is outside candidate scope or digest binding")


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


def evaluate_candidate_v2(
    candidate: LearningCandidate,
    proposal: LearningProposalManifest,
    *,
    evaluator_id: str,
    evaluation_manifest_digest: str,
    shadow_passed: bool,
    canary_passed: bool,
    now: datetime,
) -> LearningEvaluationV2:
    evaluated_at = require_utc(now)
    verify_candidate_proposal(candidate, proposal)
    if evaluated_at < candidate.matures_at:
        raise ValueError("candidate outcome has not reached its declared horizon")
    if (
        evaluator_id != proposal.independent_evaluator_id
        or evaluator_id == proposal.source_actor_id
    ):
        raise ValueError("candidate evaluation is not independent")
    if evaluation_manifest_digest != proposal.evaluation_plan_digest:
        raise ValueError("candidate evaluation does not match the locked evaluation plan")
    return LearningEvaluationV2(
        tenant_id=candidate.tenant_id,
        case_id=candidate.case_id,
        candidate_id=candidate.candidate_id,
        proposal_manifest_digest=digest_canonical(proposal),
        evaluation_manifest_digest=evaluation_manifest_digest,
        evaluator_id=evaluator_id,
        shadow_passed=shadow_passed,
        canary_passed=canary_passed,
        evaluated_at=evaluated_at,
    )


def approve_candidate_v2(
    candidate: LearningCandidate,
    proposal: LearningProposalManifest,
    evaluation: LearningEvaluationV2,
    *,
    approver_id: str,
    approver_is_human: bool,
    rollback_manifest_digest: str,
    now: datetime,
    expires_at: datetime,
) -> PromotionApprovalV2:
    approved_at = require_utc(now)
    expires_at = require_utc(expires_at)
    verify_candidate_proposal(candidate, proposal)
    if (
        evaluation.tenant_id != candidate.tenant_id
        or evaluation.case_id != candidate.case_id
        or evaluation.candidate_id != candidate.candidate_id
        or evaluation.proposal_manifest_digest != digest_canonical(proposal)
        or evaluation.evaluation_manifest_digest != proposal.evaluation_plan_digest
        or evaluation.evaluated_at < candidate.matures_at
    ):
        raise ValueError("approval evaluation is outside candidate tenant/case scope")
    if approved_at < candidate.matures_at:
        raise ValueError("candidate cannot be approved before maturity")
    if approved_at < evaluation.evaluated_at:
        raise ValueError("approval cannot precede evaluation")
    if not evaluation.shadow_passed or not evaluation.canary_passed:
        raise ValueError("candidate requires successful independent shadow and canary evaluation")
    if (
        evaluation.evaluator_id != proposal.independent_evaluator_id
        or evaluation.evaluator_id == proposal.source_actor_id
    ):
        raise ValueError("candidate evaluation is not independent")
    if not approver_is_human:
        raise ValueError("candidate approval requires an explicit human approver")
    if approver_id in {proposal.source_actor_id, evaluation.evaluator_id}:
        raise ValueError("candidate approval requires separation of duties")
    if rollback_manifest_digest != proposal.rollback_manifest_digest:
        raise ValueError("candidate approval does not bind the rollback manifest")
    return PromotionApprovalV2(
        tenant_id=candidate.tenant_id,
        case_id=candidate.case_id,
        candidate_id=candidate.candidate_id,
        proposal_manifest_digest=digest_canonical(proposal),
        proposal_digest=proposal.proposal_digest,
        evaluation_digest=digest_canonical(evaluation),
        evaluation_manifest_digest=evaluation.evaluation_manifest_digest,
        approver_id=approver_id,
        approval_digest=promotion_approval_digest(proposal, evaluation),
        rollback_manifest_digest=rollback_manifest_digest,
        approved_at=approved_at,
        not_before=approved_at,
        expires_at=expires_at,
    )
