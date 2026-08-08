"""Human-authorized promotion validation; no mutation is performed here."""

from __future__ import annotations

from aegis.contracts import (
    LearningCandidate,
    PromotionDecision,
    ValidationReport,
    canonical_sha256,
)


class PromotionDenied(RuntimeError):
    pass


def authorize_promotion(
    candidate: LearningCandidate,
    report: ValidationReport,
    decision: PromotionDecision,
) -> bool:
    candidate_hash = canonical_sha256(candidate)
    if report.candidate_id != candidate.candidate_id or report.candidate_hash != candidate_hash:
        raise PromotionDenied("validation report is not bound to the candidate")
    if report.evaluator_id == candidate.proposer_id:
        raise PromotionDenied("candidate proposer cannot evaluate its own candidate")
    if not report.passed:
        raise PromotionDenied("failed validation report cannot be promoted")
    if (
        decision.candidate_id != candidate.candidate_id
        or decision.candidate_hash != candidate_hash
        or decision.validation_report_id != report.report_id
        or decision.validation_report_hash != report.content_hash
        or decision.evaluator_id != report.evaluator_id
    ):
        raise PromotionDenied("promotion decision hash bindings do not match")
    if decision.human_approver_id == candidate.proposer_id:
        raise PromotionDenied("candidate proposer cannot approve promotion")
    return decision.decision == "promote"
