"""Offline governed-learning proposal and verification loop."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from aegisquant.contracts.common import require_utc
from aegisquant.contracts.learning import (
    LearningCandidate,
    LearningCycleResult,
    LearningEvaluationV2,
    LearningProposalManifest,
    PromotionApprovalV2,
    SignedLearningEvaluation,
    SignedPromotionApproval,
)
from aegisquant.fixture_case import FixtureCaseSpec
from aegisquant.learning.governance import (
    promotion_approval_digest,
    strategy_proposal_digest,
    verify_candidate_proposal,
)
from aegisquant.quant.multi_period import (
    MultiPeriodCaseReport,
    MultiPeriodCaseSpec,
    verify_multi_period_report,
)
from aegisquant.security.digests import digest_canonical
from aegisquant.security.learning_attestation import LearningAttestationVerifier


def propose_candidate(
    *,
    source_spec: MultiPeriodCaseSpec,
    source_report: MultiPeriodCaseReport,
    baseline_spec: FixtureCaseSpec,
    candidate_id: str,
    source_actor_id: str,
    independent_evaluator_id: str,
    evaluation_plan_digest: str,
    rollback_manifest_digest: str,
    strategy_parameter: Literal["portfolio_policy.uncertainty_floor"],
    proposed_value: Decimal,
    now: datetime,
    candidate_matures_at: datetime,
) -> LearningCycleResult:
    created_at = require_utc(now)
    if not verify_multi_period_report(source_spec, source_report):
        return LearningCycleResult(outcome="ABSTAIN", reason_code="OUTCOME_UNVERIFIED")
    if not source_report.performance.sufficient_evidence:
        return LearningCycleResult(outcome="ABSTAIN", reason_code="INSUFFICIENT_EVIDENCE")
    if created_at < source_report.periods[-1].fill_at:
        return LearningCycleResult(outcome="ABSTAIN", reason_code="OUTCOME_IMMATURE")
    if independent_evaluator_id == source_actor_id:
        return LearningCycleResult(outcome="ABSTAIN", reason_code="EVALUATION_NOT_INDEPENDENT")
    if (
        source_spec.tenant_id != baseline_spec.manifest.tenant_id
        or source_report.tenant_id != baseline_spec.manifest.tenant_id
    ):
        raise ValueError("learning source and baseline must belong to one tenant")
    proposal_digest = digest_canonical(
        {
            "strategy_parameter": strategy_parameter,
            "proposed_value": proposed_value,
        }
    )
    proposal = LearningProposalManifest(
        tenant_id=baseline_spec.manifest.tenant_id,
        case_id=baseline_spec.manifest.case_id,
        source_case_id=source_report.case_id,
        candidate_id=candidate_id,
        source_actor_id=source_actor_id,
        independent_evaluator_id=independent_evaluator_id,
        source_outcome_digest=digest_canonical(source_report),
        baseline_digest=digest_canonical(baseline_spec),
        proposal_digest=proposal_digest,
        evaluation_plan_digest=evaluation_plan_digest,
        rollback_manifest_digest=rollback_manifest_digest,
        locked_holdout_digest=source_report.locked_holdout_digest,
        strategy_parameter=strategy_parameter,
        proposed_value=proposed_value,
        created_at=created_at,
    )
    if proposal_digest != strategy_proposal_digest(proposal):
        raise ValueError("proposal digest does not bind the allowlisted strategy change")
    candidate = LearningCandidate(
        tenant_id=proposal.tenant_id,
        case_id=proposal.case_id,
        candidate_id=candidate_id,
        candidate_type="STRATEGY",
        source_manifest_digest=digest_canonical(proposal),
        created_at=created_at,
        matures_at=require_utc(candidate_matures_at),
    )
    return LearningCycleResult(
        outcome="CANDIDATE",
        reason_code="GOVERNED_CANDIDATE_CREATED",
        candidate=candidate,
        proposal=proposal,
    )


def verify_learning_records(
    candidate: LearningCandidate,
    proposal: LearningProposalManifest,
    evaluation: LearningEvaluationV2,
    approval: PromotionApprovalV2,
    *,
    source_spec: MultiPeriodCaseSpec,
    source_report: MultiPeriodCaseReport,
) -> LearningProposalManifest:
    verify_candidate_proposal(candidate, proposal)
    if (
        not verify_multi_period_report(source_spec, source_report)
        or not source_report.performance.sufficient_evidence
        or source_report.tenant_id != proposal.tenant_id
        or source_report.case_id != proposal.source_case_id
        or digest_canonical(source_report) != proposal.source_outcome_digest
        or source_report.locked_holdout_digest != proposal.locked_holdout_digest
        or source_spec.locked_holdout_digest != proposal.locked_holdout_digest
        or proposal.created_at < source_report.periods[-1].fill_at
    ):
        raise ValueError("source outcome does not authorize the learning proposal")
    proposal_manifest_digest = digest_canonical(proposal)
    if (
        evaluation.tenant_id != candidate.tenant_id
        or evaluation.case_id != candidate.case_id
        or evaluation.candidate_id != candidate.candidate_id
        or evaluation.proposal_manifest_digest != proposal_manifest_digest
        or evaluation.evaluation_manifest_digest != proposal.evaluation_plan_digest
        or evaluation.evaluator_id != proposal.independent_evaluator_id
        or evaluation.evaluator_id == proposal.source_actor_id
        or evaluation.evaluated_at < candidate.matures_at
        or not evaluation.shadow_passed
        or not evaluation.canary_passed
    ):
        raise ValueError("evaluation does not authorize the learning proposal")
    if (
        approval.tenant_id != candidate.tenant_id
        or approval.case_id != candidate.case_id
        or approval.candidate_id != candidate.candidate_id
        or approval.proposal_manifest_digest != proposal_manifest_digest
        or approval.proposal_digest != proposal.proposal_digest
        or approval.evaluation_manifest_digest != evaluation.evaluation_manifest_digest
        or approval.evaluation_digest != digest_canonical(evaluation)
        or approval.rollback_manifest_digest != proposal.rollback_manifest_digest
        or approval.approval_digest != promotion_approval_digest(proposal, evaluation)
        or approval.approver_kind != "HUMAN"
        or approval.approved_at < evaluation.evaluated_at
        or approval.approver_id in {proposal.source_actor_id, evaluation.evaluator_id}
    ):
        raise ValueError("approval does not authorize the learning proposal")
    return proposal


def verify_approved_candidate(
    candidate: LearningCandidate,
    proposal: LearningProposalManifest,
    signed_evaluation: SignedLearningEvaluation,
    signed_approval: SignedPromotionApproval,
    *,
    source_spec: MultiPeriodCaseSpec,
    source_report: MultiPeriodCaseReport,
    attestation_verifier: LearningAttestationVerifier,
    now: datetime,
) -> LearningProposalManifest:
    evaluation = attestation_verifier.verify_evaluation(signed_evaluation, now=now)
    approval = attestation_verifier.verify_approval(signed_approval, now=now)
    return verify_learning_records(
        candidate,
        proposal,
        evaluation,
        approval,
        source_spec=source_spec,
        source_report=source_report,
    )


def apply_approved_strategy_candidate(
    spec: FixtureCaseSpec,
    *,
    candidate: LearningCandidate,
    proposal: LearningProposalManifest,
    signed_evaluation: SignedLearningEvaluation,
    signed_approval: SignedPromotionApproval,
    source_spec: MultiPeriodCaseSpec,
    source_report: MultiPeriodCaseReport,
    attestation_verifier: LearningAttestationVerifier,
    now: datetime,
) -> FixtureCaseSpec:
    verified = verify_approved_candidate(
        candidate,
        proposal,
        signed_evaluation,
        signed_approval,
        source_spec=source_spec,
        source_report=source_report,
        attestation_verifier=attestation_verifier,
        now=now,
    )
    if spec.manifest.tenant_id != verified.tenant_id:
        raise ValueError("baseline fixture is outside the approved tenant")
    if spec.manifest.case_id != verified.case_id:
        raise ValueError("baseline fixture is outside the approved case")
    if digest_canonical(spec) != verified.baseline_digest:
        raise ValueError("baseline fixture digest does not match the approved proposal")
    if verified.strategy_parameter != "portfolio_policy.uncertainty_floor":
        raise ValueError("strategy parameter is not allowlisted")
    data = spec.model_dump(mode="python")
    data["portfolio_policy"]["uncertainty_floor"] = verified.proposed_value
    return FixtureCaseSpec.model_validate(data)
