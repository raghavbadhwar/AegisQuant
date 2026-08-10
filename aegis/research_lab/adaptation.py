"""Candidate-only belief adaptation contracts backed by a local evidence index."""

from __future__ import annotations

from itertools import pairwise
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from aegis.causal.beliefs import BeliefRevision
from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel
from aegis.research_lab.adaptive_evidence import (
    AdaptiveEvidenceCheckpoint,
    AdaptiveEvidenceIndex,
    AdaptiveEvidenceRecord,
)

_SHA256 = r"^[0-9a-f]{64}$"
_EVALUATOR_ID = "registered-rational-fixture-1"
_EVALUATOR_DIGEST = canonical_sha256(
    {"evaluator_id": _EVALUATOR_ID, "implementation": "integer-rational-v1"}
)
_RUNTIME_FINGERPRINT = "python-3.12-integer-rational-v1"


def _required_content_hash(value: str | None) -> str:
    if value is None:
        raise ValueError("adaptive contract must be sealed")
    return value


class _SealedAdaptiveModel(CandidateContractModel):
    content_hash: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def has_valid_content_hash(self) -> Self:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("adaptive contract content hash mismatch")
        return self

    def sealed(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = type(self).model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class AdaptiveTargetEnvelope(_SealedAdaptiveModel):
    """Receipt-referenced metadata around one belief lineage target.

    Labels are local declarations only; this contract does not authenticate identity.
    """

    target_id: str = Field(min_length=1)
    target_kind: Literal["belief_posterior"] = "belief_posterior"
    basis_revision_hash: str = Field(pattern=_SHA256)
    origin_receipt_id: str = Field(min_length=1)
    origin_receipt_hash: str = Field(pattern=_SHA256)
    declared_origin_label: str = Field(min_length=1)
    revision_proposer_label: str = Field(min_length=1)
    version: int = Field(ge=1)
    parent_envelope_hash: str | None = Field(default=None, pattern=_SHA256)
    authority: Literal["candidate_only"] = "candidate_only"
    evidence_status: Literal["engineering_only"] = "engineering_only"
    release_status: Literal["release_gated"] = "release_gated"

    @model_validator(mode="after")
    def has_linear_initial_lineage(self) -> AdaptiveTargetEnvelope:
        if self.declared_origin_label == self.revision_proposer_label:
            raise ValueError("adaptive target origin and proposer labels must differ")
        if (self.version == 1) != (self.parent_envelope_hash is None):
            raise ValueError("adaptive target envelope parent must match version")
        return self


class AdaptationPolicy(_SealedAdaptiveModel):
    """Frozen local policy for one bounded candidate belief update."""

    policy_id: str = Field(min_length=1)
    as_of: AwareDatetime
    max_probability_delta: float = Field(gt=0.0, le=1.0, allow_inf_nan=False)
    policy_deadline: AwareDatetime
    authority: Literal["candidate_only"] = "candidate_only"
    evidence_status: Literal["engineering_only"] = "engineering_only"
    release_status: Literal["release_gated"] = "release_gated"

    @model_validator(mode="after")
    def has_nonexpired_creation_window(self) -> AdaptationPolicy:
        if self.policy_deadline < self.as_of:
            raise ValueError("adaptive policy deadline is before its cutoff")
        return self


class AdaptationProposal(_SealedAdaptiveModel):
    """One bounded candidate belief revision; it cannot mutate a belief ledger."""

    proposal_id: str = Field(min_length=1)
    as_of: AwareDatetime
    envelope: AdaptiveTargetEnvelope
    prior: BeliefRevision
    proposed: BeliefRevision
    policy: AdaptationPolicy
    evidence_checkpoint: AdaptiveEvidenceCheckpoint
    evidence_records: tuple[AdaptiveEvidenceRecord, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    evidence_hashes: tuple[str, ...] = Field(min_length=1)
    prior_revision_hash: str = Field(pattern=_SHA256)
    proposed_revision_hash: str = Field(pattern=_SHA256)
    authority: Literal["candidate_only"] = "candidate_only"
    evidence_status: Literal["engineering_only"] = "engineering_only"
    release_status: Literal["release_gated"] = "release_gated"

    @model_validator(mode="after")
    def binds_exact_belief_successor_and_evidence(self) -> AdaptationProposal:
        envelope = AdaptiveTargetEnvelope.model_validate(self.envelope.model_dump(mode="json"))
        prior = BeliefRevision.model_validate(self.prior.model_dump(mode="json"))
        proposed = BeliefRevision.model_validate(self.proposed.model_dump(mode="json"))
        policy = AdaptationPolicy.model_validate(self.policy.model_dump(mode="json"))
        checkpoint = AdaptiveEvidenceCheckpoint.model_validate(
            self.evidence_checkpoint.model_dump(mode="json")
        )
        records = tuple(
            AdaptiveEvidenceRecord.model_validate(record.model_dump(mode="json"))
            for record in self.evidence_records
        )
        if any(
            item.content_hash is None for item in (envelope, prior, proposed, policy, checkpoint)
        ):
            raise ValueError("adaptive proposal requires sealed nested contracts")
        if self.as_of != policy.as_of or self.as_of != checkpoint.as_of:
            raise ValueError("adaptive proposal cutoff must bind policy and evidence checkpoint")
        if self.as_of > policy.policy_deadline:
            raise ValueError("adaptive proposal is after its policy deadline")
        if prior.as_of > self.as_of or proposed.as_of > self.as_of:
            raise ValueError("adaptive belief revisions must not be after proposal cutoff")
        if (
            envelope.basis_revision_hash != prior.content_hash
            or self.prior_revision_hash != prior.content_hash
        ):
            raise ValueError("adaptive proposal prior revision hash mismatch")
        if self.proposed_revision_hash != proposed.content_hash:
            raise ValueError("adaptive proposal proposed revision hash mismatch")
        if (
            proposed.belief_id != prior.belief_id
            or proposed.sequence != prior.sequence + 1
            or proposed.parent_revision_hash != prior.content_hash
            or proposed.prior_probability != prior.posterior_probability
        ):
            raise ValueError("adaptive proposal must contain one exact belief successor")
        if (
            abs(proposed.posterior_probability - prior.posterior_probability)
            > policy.max_probability_delta
        ):
            raise ValueError("adaptive proposal belief delta exceeds policy")
        if (
            self.evidence_ids != checkpoint.record_ids
            or self.evidence_hashes != checkpoint.record_hashes
        ):
            raise ValueError("adaptive proposal evidence set must equal its checkpoint")
        if tuple(record.evidence_id for record in records) != tuple(sorted(self.evidence_ids)):
            raise ValueError("adaptive proposal evidence records must match IDs")
        record_hashes = {
            record.evidence_id: _required_content_hash(record.content_hash) for record in records
        }
        if (
            tuple(record_hashes[evidence_id] for evidence_id in self.evidence_ids)
            != self.evidence_hashes
        ):
            raise ValueError("adaptive proposal evidence records must match hashes")
        if proposed.evidence_ids != self.evidence_ids:
            raise ValueError("adaptive proposal belief evidence IDs must equal its checkpoint")
        return self


def build_belief_adaptation_proposal(
    *,
    proposal_id: str,
    index: AdaptiveEvidenceIndex,
    as_of: AwareDatetime,
    envelope: AdaptiveTargetEnvelope,
    prior: BeliefRevision,
    proposed: BeliefRevision,
    policy: AdaptationPolicy,
) -> AdaptationProposal:
    """Build one proposal from the index's reconstructed evidence root only."""

    checkpoint = index.checkpoint(as_of)
    resolved = index.resolve(
        as_of=as_of,
        record_kinds=("verification", "negative_result", "refutation"),
    )
    if tuple(record.evidence_id for record in resolved) != tuple(sorted(checkpoint.record_ids)):
        raise ValueError("adaptive evidence resolution does not reconcile to checkpoint IDs")
    by_id = {record.evidence_id: record for record in resolved}
    evidence_ids = checkpoint.record_ids
    evidence_hashes = tuple(
        _required_content_hash(by_id[evidence_id].content_hash) for evidence_id in evidence_ids
    )
    if evidence_hashes != checkpoint.record_hashes:
        raise ValueError("adaptive evidence resolution does not reconcile to checkpoint hashes")
    return AdaptationProposal(
        proposal_id=proposal_id,
        as_of=as_of,
        envelope=envelope,
        prior=prior,
        proposed=proposed,
        policy=policy,
        evidence_checkpoint=checkpoint,
        evidence_records=resolved,
        evidence_ids=evidence_ids,
        evidence_hashes=evidence_hashes,
        prior_revision_hash=_required_content_hash(prior.content_hash),
        proposed_revision_hash=_required_content_hash(proposed.content_hash),
    ).sealed()


class AdaptiveEvaluationManifest(_SealedAdaptiveModel):
    """Preregistered integer fixture inputs for a closed evaluator."""

    manifest_id: str = Field(min_length=1)
    proposal: AdaptationProposal
    evaluator_id: Literal["registered-rational-fixture-1"] = "registered-rational-fixture-1"
    evaluator_digest: str = Field(default=_EVALUATOR_DIGEST, pattern=_SHA256)
    runtime_fingerprint: Literal["python-3.12-integer-rational-v1"] = (
        "python-3.12-integer-rational-v1"
    )
    candidate_primary_score: int
    incumbent_primary_score: int
    candidate_protected_score: int
    incumbent_protected_score: int
    primary_threshold: int = Field(ge=0)
    protected_regression_tolerance: int = Field(ge=0)
    authority: Literal["candidate_only"] = "candidate_only"
    evidence_status: Literal["engineering_only"] = "engineering_only"
    release_status: Literal["release_gated"] = "release_gated"

    @model_validator(mode="after")
    def binds_registered_inputs(self) -> AdaptiveEvaluationManifest:
        proposal = AdaptationProposal.model_validate(self.proposal.model_dump(mode="json"))
        if proposal.content_hash is None:
            raise ValueError("adaptive evaluation manifest requires a sealed proposal")
        if self.evaluator_digest != _EVALUATOR_DIGEST:
            raise ValueError("adaptive evaluation manifest evaluator digest is unavailable")
        return self


class AdaptiveEvaluationResult(_SealedAdaptiveModel):
    """Derived closed-fixture outcome; callers cannot choose its computed fields."""

    manifest: AdaptiveEvaluationManifest
    primary_delta: int
    protected_delta: int
    disposition: Literal["advance_for_human_review", "retain_incumbent"]
    authority: Literal["candidate_only"] = "candidate_only"
    evidence_status: Literal["engineering_only"] = "engineering_only"
    release_status: Literal["release_gated"] = "release_gated"

    @model_validator(mode="after")
    def exactly_recomputes_registered_fixture(self) -> AdaptiveEvaluationResult:
        manifest = AdaptiveEvaluationManifest.model_validate(self.manifest.model_dump(mode="json"))
        if manifest.content_hash is None:
            raise ValueError("adaptive evaluation result requires a sealed manifest")
        primary_delta, protected_delta, disposition = _evaluate_fixture(manifest)
        if (self.primary_delta, self.protected_delta, self.disposition) != (
            primary_delta,
            protected_delta,
            disposition,
        ):
            raise ValueError("adaptive evaluation result does not match registered fixture")
        return self


def _evaluate_fixture(
    manifest: AdaptiveEvaluationManifest,
) -> tuple[int, int, Literal["advance_for_human_review", "retain_incumbent"]]:
    primary_delta = manifest.candidate_primary_score - manifest.incumbent_primary_score
    protected_delta = manifest.candidate_protected_score - manifest.incumbent_protected_score
    disposition: Literal["advance_for_human_review", "retain_incumbent"]
    if (
        primary_delta >= manifest.primary_threshold
        and protected_delta >= -manifest.protected_regression_tolerance
    ):
        disposition = "advance_for_human_review"
    else:
        disposition = "retain_incumbent"
    return primary_delta, protected_delta, disposition


def evaluate_registered_adaptive_fixture(
    manifest: AdaptiveEvaluationManifest,
) -> AdaptiveEvaluationResult:
    """Evaluate the sole registered integer fixture without caller-provided outcomes."""

    validated = AdaptiveEvaluationManifest.model_validate(manifest.model_dump(mode="json"))
    if validated.content_hash is None:
        raise ValueError("adaptive evaluation manifest must be sealed")
    if (
        validated.evaluator_id != _EVALUATOR_ID
        or validated.evaluator_digest != _EVALUATOR_DIGEST
        or validated.runtime_fingerprint != _RUNTIME_FINGERPRINT
    ):
        raise ValueError("registered adaptive evaluator is unavailable")
    primary_delta, protected_delta, disposition = _evaluate_fixture(validated)
    return AdaptiveEvaluationResult(
        manifest=validated,
        primary_delta=primary_delta,
        protected_delta=protected_delta,
        disposition=disposition,
    ).sealed()


class CandidateRecommendation(_SealedAdaptiveModel):
    """Read-only candidate recommendation with no active/champion state pointer."""

    recommendation_id: str = Field(min_length=1)
    as_of: AwareDatetime
    result: AdaptiveEvaluationResult
    evidence_checkpoint: AdaptiveEvidenceCheckpoint
    evidence_records: tuple[AdaptiveEvidenceRecord, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    evidence_hashes: tuple[str, ...] = Field(min_length=1)
    blocking_evidence_ids: tuple[str, ...] = ()
    disposition: Literal["advance_for_human_review", "retain_incumbent"]
    reason: str = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"
    evidence_status: Literal["engineering_only"] = "engineering_only"
    release_status: Literal["release_gated"] = "release_gated"

    @model_validator(mode="after")
    def binds_result_and_complete_local_checkpoint(self) -> CandidateRecommendation:
        result = AdaptiveEvaluationResult.model_validate(self.result.model_dump(mode="json"))
        checkpoint = AdaptiveEvidenceCheckpoint.model_validate(
            self.evidence_checkpoint.model_dump(mode="json")
        )
        records = tuple(
            AdaptiveEvidenceRecord.model_validate(record.model_dump(mode="json"))
            for record in self.evidence_records
        )
        records = tuple(
            AdaptiveEvidenceRecord.model_validate(record.model_dump(mode="json"))
            for record in self.evidence_records
        )
        if result.content_hash is None or checkpoint.content_hash is None:
            raise ValueError("candidate recommendation requires sealed result and checkpoint")
        if self.as_of != checkpoint.as_of:
            raise ValueError("candidate recommendation cutoff must match checkpoint")
        if (
            self.evidence_ids != checkpoint.record_ids
            or self.evidence_hashes != checkpoint.record_hashes
        ):
            raise ValueError("candidate recommendation evidence set must equal checkpoint")
        if tuple(record.evidence_id for record in records) != tuple(sorted(self.evidence_ids)):
            raise ValueError("candidate recommendation evidence records must match IDs")
        record_hashes = {
            record.evidence_id: _required_content_hash(record.content_hash) for record in records
        }
        if (
            tuple(record_hashes[evidence_id] for evidence_id in self.evidence_ids)
            != self.evidence_hashes
        ):
            raise ValueError("candidate recommendation evidence records must match hashes")
        expected_blocking = tuple(
            record.evidence_id
            for record in records
            if record.record_kind in {"negative_result", "refutation"}
        )
        if self.blocking_evidence_ids != expected_blocking:
            raise ValueError("candidate recommendation blocking evidence must be complete")
        if not set(result.manifest.proposal.evidence_ids).issubset(self.evidence_ids):
            raise ValueError("candidate recommendation cannot omit proposal evidence")
        if self.blocking_evidence_ids:
            if (
                self.disposition != "retain_incumbent"
                or self.reason != "unresolved_negative_or_refutation"
            ):
                raise ValueError("blocking adaptive evidence must retain the incumbent")
        elif self.disposition != result.disposition:
            raise ValueError("candidate recommendation must equal its fixture result")
        return self


def build_candidate_recommendation(
    *,
    recommendation_id: str,
    index: AdaptiveEvidenceIndex,
    as_of: AwareDatetime,
    result: AdaptiveEvaluationResult,
) -> CandidateRecommendation:
    """Build a recommendation from all locally indexed evidence at its cutoff."""

    checkpoint = index.checkpoint(as_of)
    resolved = index.resolve(
        as_of=as_of,
        record_kinds=("verification", "negative_result", "refutation"),
    )
    by_id = {record.evidence_id: record for record in resolved}
    evidence_hashes = tuple(
        _required_content_hash(by_id[evidence_id].content_hash)
        for evidence_id in checkpoint.record_ids
    )
    if evidence_hashes != checkpoint.record_hashes:
        raise ValueError("candidate recommendation evidence does not reconcile to checkpoint")
    blocking = tuple(
        record.evidence_id
        for record in resolved
        if record.record_kind in {"negative_result", "refutation"}
    )
    disposition: Literal["advance_for_human_review", "retain_incumbent"]
    reason: str
    if blocking:
        disposition = "retain_incumbent"
        reason = "unresolved_negative_or_refutation"
    else:
        disposition = result.disposition
        reason = "registered_fixture_result"
    return CandidateRecommendation(
        recommendation_id=recommendation_id,
        as_of=as_of,
        result=result,
        evidence_checkpoint=checkpoint,
        evidence_records=resolved,
        evidence_ids=checkpoint.record_ids,
        evidence_hashes=evidence_hashes,
        blocking_evidence_ids=blocking,
        disposition=disposition,
        reason=reason,
    ).sealed()


AdaptiveLoopStopReason = Literal[
    "iteration_cap",
    "cycle_detected",
    "budget_exhausted",
    "deadline_reached",
    "non_positive_voi",
    "decision_robust",
    "non_decision_changing_uncertainty",
]


class AdaptiveLoopPolicy(_SealedAdaptiveModel):
    """Frozen logical bounds for the no-I/O candidate history builder."""

    policy_id: str = Field(min_length=1)
    as_of: AwareDatetime
    max_iterations: int = Field(ge=1, le=16)
    budget_units: int = Field(ge=0)
    deadline_reached: bool
    decision_robust: bool
    uncertainty_can_change_decision: bool
    authority: Literal["candidate_only"] = "candidate_only"
    evidence_status: Literal["engineering_only"] = "engineering_only"
    release_status: Literal["release_gated"] = "release_gated"


class AdaptiveHistoryEntry(_SealedAdaptiveModel):
    """One immutable candidate recommendation in linear adaptive history."""

    sequence: int = Field(ge=1)
    recommendation: CandidateRecommendation
    predecessor_hash: str | None = Field(default=None, pattern=_SHA256)
    iteration_cost_units: int = Field(ge=0)
    expected_voi_units: int
    authority: Literal["candidate_only"] = "candidate_only"
    evidence_status: Literal["engineering_only"] = "engineering_only"
    release_status: Literal["release_gated"] = "release_gated"

    @model_validator(mode="after")
    def binds_sealed_recommendation(self) -> AdaptiveHistoryEntry:
        recommendation = CandidateRecommendation.model_validate(
            self.recommendation.model_dump(mode="json")
        )
        if recommendation.content_hash is None:
            raise ValueError("adaptive history entry requires a sealed recommendation")
        if self.sequence == 1 and self.predecessor_hash is not None:
            raise ValueError("first adaptive history entry cannot have a predecessor")
        if self.sequence > 1 and self.predecessor_hash is None:
            raise ValueError("later adaptive history entry requires a predecessor")
        return self


class AdaptiveHistory(_SealedAdaptiveModel):
    """Bounded append-only candidate history; it never advances a live state."""

    history_id: str = Field(min_length=1)
    policy: AdaptiveLoopPolicy
    entries: tuple[AdaptiveHistoryEntry, ...] = ()
    total_cost_units: int = Field(ge=0)
    stop_reason: AdaptiveLoopStopReason | None = None
    cycle_attempt: CandidateRecommendation | None = None
    budget_blocked_attempt: AdaptiveHistoryEntry | None = None
    authority: Literal["candidate_only"] = "candidate_only"
    evidence_status: Literal["engineering_only"] = "engineering_only"
    release_status: Literal["release_gated"] = "release_gated"

    @model_validator(mode="after")
    def has_exact_linear_history_and_stop(self) -> AdaptiveHistory:
        policy = AdaptiveLoopPolicy.model_validate(self.policy.model_dump(mode="json"))
        entries = tuple(
            AdaptiveHistoryEntry.model_validate(entry.model_dump(mode="json"))
            for entry in self.entries
        )
        if policy.content_hash is None or any(entry.content_hash is None for entry in entries):
            raise ValueError("adaptive history requires sealed policy and entries")
        if any(entry.recommendation.as_of > policy.as_of for entry in entries):
            raise ValueError("adaptive history recommendation is after policy cutoff")
        if [entry.sequence for entry in entries] != list(range(1, len(entries) + 1)):
            raise ValueError("adaptive history entry sequences must be contiguous")
        if len(entries) > policy.max_iterations:
            raise ValueError("adaptive history exceeds iteration cap")
        for previous, current in pairwise(entries):
            if current.predecessor_hash != previous.content_hash:
                raise ValueError("adaptive history predecessor hash mismatch")
        recommendation_hashes = [
            _required_content_hash(entry.recommendation.content_hash) for entry in entries
        ]
        if len(recommendation_hashes) != len(set(recommendation_hashes)):
            raise ValueError("adaptive history cannot append a recommendation cycle")
        if self.total_cost_units != sum(entry.iteration_cost_units for entry in entries):
            raise ValueError("adaptive history total cost must reconcile exactly")
        expected_stop = _adaptive_history_stop_reason(policy, entries)
        if self.total_cost_units > policy.budget_units:
            raise ValueError("adaptive history cannot exceed its budget")
        if self.cycle_attempt is not None:
            attempted = CandidateRecommendation.model_validate(
                self.cycle_attempt.model_dump(mode="json")
            )
            attempted_hash = _required_content_hash(attempted.content_hash)
            if expected_stop is not None:
                raise ValueError("adaptive history cannot override a bounded stop with a cycle")
            if attempted_hash not in recommendation_hashes:
                raise ValueError("adaptive history cycle attempt must reference an existing entry")
            expected_stop = "cycle_detected"
        elif self.stop_reason == "cycle_detected":
            raise ValueError("adaptive history cycle stop requires a recorded cycle attempt")
        if self.budget_blocked_attempt is not None:
            blocked = AdaptiveHistoryEntry.model_validate(
                self.budget_blocked_attempt.model_dump(mode="json")
            )
            if blocked.recommendation.as_of > policy.as_of:
                raise ValueError("adaptive history blocked recommendation is after policy cutoff")
            if expected_stop is not None:
                raise ValueError(
                    "adaptive history cannot override a bounded stop with a budget block"
                )
            if blocked.sequence != len(entries) + 1 or blocked.predecessor_hash != (
                entries[-1].content_hash if entries else None
            ):
                raise ValueError("adaptive history blocked attempt must extend the exact lineage")
            if _required_content_hash(blocked.recommendation.content_hash) in recommendation_hashes:
                raise ValueError("adaptive history blocked attempt cannot repeat a recommendation")
            if self.total_cost_units + blocked.iteration_cost_units <= policy.budget_units:
                raise ValueError("adaptive history budget block must exceed remaining budget")
            expected_stop = "budget_exhausted"
        elif self.stop_reason == "budget_exhausted" and expected_stop != "budget_exhausted":
            raise ValueError("adaptive history budget stop requires a blocked iteration")
        if self.stop_reason != expected_stop:
            raise ValueError("adaptive history stop reason does not match bounded inputs")
        return self


def _adaptive_history_stop_reason(
    policy: AdaptiveLoopPolicy, entries: tuple[AdaptiveHistoryEntry, ...]
) -> AdaptiveLoopStopReason | None:
    if policy.deadline_reached:
        return "deadline_reached"
    if sum(entry.iteration_cost_units for entry in entries) >= policy.budget_units:
        return "budget_exhausted"
    if policy.decision_robust:
        return "decision_robust"
    if not policy.uncertainty_can_change_decision:
        return "non_decision_changing_uncertainty"
    if any(entry.expected_voi_units <= 0 for entry in entries):
        return "non_positive_voi"
    if len(entries) >= policy.max_iterations:
        return "iteration_cap"
    return None


def build_adaptive_history(
    *,
    policy: AdaptiveLoopPolicy,
    recommendations: tuple[CandidateRecommendation, ...],
    iteration_cost_units: tuple[int, ...],
    expected_voi_units: tuple[int, ...],
    history_id: str = "adaptive-history",
) -> AdaptiveHistory:
    """Build a bounded, deterministic candidate history from sealed recommendations only."""

    validated_policy = AdaptiveLoopPolicy.model_validate(policy.model_dump(mode="json"))
    validated_recommendations = tuple(
        CandidateRecommendation.model_validate(recommendation.model_dump(mode="json"))
        for recommendation in recommendations
    )
    if validated_policy.content_hash is None or any(
        recommendation.content_hash is None for recommendation in validated_recommendations
    ):
        raise ValueError("adaptive history builder requires sealed policy and recommendations")
    if (
        not (len(validated_recommendations) == len(iteration_cost_units) == len(expected_voi_units))
        or not validated_recommendations
    ):
        raise ValueError("adaptive history inputs must be nonempty and equal length")
    entries: list[AdaptiveHistoryEntry] = []
    seen_recommendations: set[str] = set()
    cycle_attempt: CandidateRecommendation | None = None
    budget_blocked_attempt: AdaptiveHistoryEntry | None = None
    for recommendation, cost, voi in zip(
        validated_recommendations, iteration_cost_units, expected_voi_units, strict=True
    ):
        if _adaptive_history_stop_reason(validated_policy, tuple(entries)) is not None:
            break
        recommendation_hash = _required_content_hash(recommendation.content_hash)
        if recommendation_hash in seen_recommendations:
            cycle_attempt = recommendation
            break
        if len(entries) >= validated_policy.max_iterations:
            break
        if (
            sum(entry.iteration_cost_units for entry in entries) + cost
            > validated_policy.budget_units
        ):
            budget_blocked_attempt = AdaptiveHistoryEntry(
                sequence=len(entries) + 1,
                recommendation=recommendation,
                predecessor_hash=entries[-1].content_hash if entries else None,
                iteration_cost_units=cost,
                expected_voi_units=voi,
            ).sealed()
            break
        entries.append(
            AdaptiveHistoryEntry(
                sequence=len(entries) + 1,
                recommendation=recommendation,
                predecessor_hash=entries[-1].content_hash if entries else None,
                iteration_cost_units=cost,
                expected_voi_units=voi,
            ).sealed()
        )
        seen_recommendations.add(recommendation_hash)
        if _adaptive_history_stop_reason(validated_policy, tuple(entries)) is not None:
            break
    expected_stop = _adaptive_history_stop_reason(validated_policy, tuple(entries))
    if cycle_attempt is not None:
        expected_stop = "cycle_detected"
    elif budget_blocked_attempt is not None:
        expected_stop = "budget_exhausted"
    return AdaptiveHistory(
        history_id=history_id,
        policy=validated_policy,
        entries=tuple(entries),
        total_cost_units=sum(entry.iteration_cost_units for entry in entries),
        stop_reason=expected_stop,
        cycle_attempt=cycle_attempt,
        budget_blocked_attempt=budget_blocked_attempt,
    ).sealed()
