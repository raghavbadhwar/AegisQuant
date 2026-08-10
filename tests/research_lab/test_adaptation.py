from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aegis.causal.beliefs import BeliefRevision
from aegis.contracts import canonical_sha256
from aegis.research_lab.adaptation import (
    AdaptationPolicy,
    AdaptiveEvaluationManifest,
    AdaptiveTargetEnvelope,
    CandidateRecommendation,
    build_belief_adaptation_proposal,
    build_candidate_recommendation,
    evaluate_registered_adaptive_fixture,
)
from aegis.research_lab.adaptive_evidence import AdaptiveEvidenceIndex, AdaptiveEvidenceRecord


def test_belief_adaptation_proposal_rebuilds_its_evidence_set(tmp_path) -> None:
    as_of = datetime(2026, 1, 15, tzinfo=UTC)
    index = AdaptiveEvidenceIndex(tmp_path / "adaptive-evidence.sqlite")
    payload = {"verification_package_id": "verification-1"}
    receipt_payload = {"receipt_id": "receipt-1", "observed_at": as_of.isoformat()}
    index.append(
        AdaptiveEvidenceRecord(
            evidence_id="verification-1",
            record_kind="verification",
            payload=payload,
            payload_content_hash=canonical_sha256(payload),
            receipt_id="receipt-1",
            receipt_payload=receipt_payload,
            receipt_content_hash=canonical_sha256(receipt_payload),
            observed_at=as_of,
        ).sealed()
    )
    prior = BeliefRevision(
        revision_id="belief-revision-1",
        belief_id="belief-1",
        sequence=1,
        as_of=as_of,
        prior_probability=0.4,
        posterior_probability=0.4,
        assumption_ids=("assumption-1",),
    ).sealed()
    proposed = BeliefRevision(
        revision_id="belief-revision-2",
        belief_id="belief-1",
        sequence=2,
        as_of=as_of,
        prior_probability=0.4,
        posterior_probability=0.5,
        evidence_ids=("verification-1",),
        assumption_ids=("assumption-1",),
        parent_revision_hash=prior.content_hash,
    ).sealed()
    envelope = AdaptiveTargetEnvelope(
        target_id="belief-target-1",
        basis_revision_hash=prior.content_hash,
        origin_receipt_id="origin-receipt-1",
        origin_receipt_hash="b" * 64,
        declared_origin_label="researcher-1",
        revision_proposer_label="researcher-2",
        version=1,
    ).sealed()
    policy = AdaptationPolicy(
        policy_id="policy-1",
        as_of=as_of,
        max_probability_delta=0.2,
        policy_deadline=as_of,
    ).sealed()

    proposal = build_belief_adaptation_proposal(
        proposal_id="proposal-1",
        index=index,
        as_of=as_of,
        envelope=envelope,
        prior=prior,
        proposed=proposed,
        policy=policy,
    )

    assert proposal.evidence_ids == ("verification-1",)
    assert proposal.prior_revision_hash == prior.content_hash
    assert proposal.proposed_revision_hash == proposed.content_hash
    assert proposal.content_hash is not None


def test_registered_adaptive_fixture_recomputes_a_byte_stable_result(tmp_path) -> None:
    as_of = datetime(2026, 1, 15, tzinfo=UTC)
    index = AdaptiveEvidenceIndex(tmp_path / "adaptive-evidence.sqlite")
    payload = {"verification_package_id": "verification-1"}
    receipt_payload = {"receipt_id": "receipt-1", "observed_at": as_of.isoformat()}
    index.append(
        AdaptiveEvidenceRecord(
            evidence_id="verification-1",
            record_kind="verification",
            payload=payload,
            payload_content_hash=canonical_sha256(payload),
            receipt_id="receipt-1",
            receipt_payload=receipt_payload,
            receipt_content_hash=canonical_sha256(receipt_payload),
            observed_at=as_of,
        ).sealed()
    )
    prior = BeliefRevision(
        revision_id="belief-revision-1",
        belief_id="belief-1",
        sequence=1,
        as_of=as_of,
        prior_probability=0.4,
        posterior_probability=0.4,
        assumption_ids=("assumption-1",),
    ).sealed()
    proposed = BeliefRevision(
        revision_id="belief-revision-2",
        belief_id="belief-1",
        sequence=2,
        as_of=as_of,
        prior_probability=0.4,
        posterior_probability=0.5,
        evidence_ids=("verification-1",),
        assumption_ids=("assumption-1",),
        parent_revision_hash=prior.content_hash,
    ).sealed()
    proposal = build_belief_adaptation_proposal(
        proposal_id="proposal-1",
        index=index,
        as_of=as_of,
        envelope=AdaptiveTargetEnvelope(
            target_id="belief-target-1",
            basis_revision_hash=prior.content_hash,
            origin_receipt_id="origin-receipt-1",
            origin_receipt_hash="b" * 64,
            declared_origin_label="researcher-1",
            revision_proposer_label="researcher-2",
            version=1,
        ).sealed(),
        prior=prior,
        proposed=proposed,
        policy=AdaptationPolicy(
            policy_id="policy-1",
            as_of=as_of,
            max_probability_delta=0.2,
            policy_deadline=as_of,
        ).sealed(),
    )
    manifest = AdaptiveEvaluationManifest(
        manifest_id="manifest-1",
        proposal=proposal,
        candidate_primary_score=11,
        incumbent_primary_score=10,
        candidate_protected_score=10,
        incumbent_protected_score=10,
        primary_threshold=1,
        protected_regression_tolerance=0,
    ).sealed()

    first = evaluate_registered_adaptive_fixture(manifest)
    second = evaluate_registered_adaptive_fixture(manifest)

    assert first.disposition == "advance_for_human_review"
    assert first.model_dump_json() == second.model_dump_json()


def test_recommendation_retains_incumbent_when_cutoff_contains_negative_evidence(tmp_path) -> None:
    as_of = datetime(2026, 1, 15, tzinfo=UTC)
    index = AdaptiveEvidenceIndex(tmp_path / "adaptive-evidence.sqlite")
    for evidence_id, record_kind in (
        ("verification-1", "verification"),
        ("negative-1", "negative_result"),
    ):
        payload = {"evidence_id": evidence_id}
        receipt_payload = {"receipt_id": f"receipt-{evidence_id}", "observed_at": as_of.isoformat()}
        index.append(
            AdaptiveEvidenceRecord(
                evidence_id=evidence_id,
                record_kind=record_kind,
                payload=payload,
                payload_content_hash=canonical_sha256(payload),
                receipt_id=f"receipt-{evidence_id}",
                receipt_payload=receipt_payload,
                receipt_content_hash=canonical_sha256(receipt_payload),
                observed_at=as_of,
            ).sealed()
        )
    prior = BeliefRevision(
        revision_id="belief-revision-1",
        belief_id="belief-1",
        sequence=1,
        as_of=as_of,
        prior_probability=0.4,
        posterior_probability=0.4,
        assumption_ids=("assumption-1",),
    ).sealed()
    proposed = BeliefRevision(
        revision_id="belief-revision-2",
        belief_id="belief-1",
        sequence=2,
        as_of=as_of,
        prior_probability=0.4,
        posterior_probability=0.5,
        evidence_ids=("verification-1", "negative-1"),
        assumption_ids=("assumption-1",),
        parent_revision_hash=prior.content_hash,
    ).sealed()
    proposal = build_belief_adaptation_proposal(
        proposal_id="proposal-1",
        index=index,
        as_of=as_of,
        envelope=AdaptiveTargetEnvelope(
            target_id="belief-target-1",
            basis_revision_hash=prior.content_hash,
            origin_receipt_id="origin-receipt-1",
            origin_receipt_hash="b" * 64,
            declared_origin_label="researcher-1",
            revision_proposer_label="researcher-2",
            version=1,
        ).sealed(),
        prior=prior,
        proposed=proposed,
        policy=AdaptationPolicy(
            policy_id="policy-1",
            as_of=as_of,
            max_probability_delta=0.2,
            policy_deadline=as_of,
        ).sealed(),
    )
    result = evaluate_registered_adaptive_fixture(
        AdaptiveEvaluationManifest(
            manifest_id="manifest-1",
            proposal=proposal,
            candidate_primary_score=11,
            incumbent_primary_score=10,
            candidate_protected_score=10,
            incumbent_protected_score=10,
            primary_threshold=1,
            protected_regression_tolerance=0,
        ).sealed()
    )

    recommendation = build_candidate_recommendation(
        recommendation_id="recommendation-1",
        index=index,
        as_of=as_of,
        result=result,
    )

    assert recommendation.disposition == "retain_incumbent"
    assert recommendation.reason == "unresolved_negative_or_refutation"

    forged = recommendation.model_dump(mode="json", exclude={"content_hash"})
    forged["blocking_evidence_ids"] = ()
    with pytest.raises(ValueError, match="blocking evidence must be complete"):
        CandidateRecommendation.model_validate(forged)


def test_adaptive_contract_surface_is_public() -> None:
    from aegis.research_lab import (
        AdaptationPolicy,
        AdaptiveEvidenceIndex,
        CandidateRecommendation,
        build_candidate_recommendation,
    )

    assert AdaptationPolicy.__name__ == "AdaptationPolicy"
    assert AdaptiveEvidenceIndex.__name__ == "AdaptiveEvidenceIndex"
    assert CandidateRecommendation.__name__ == "CandidateRecommendation"
    assert callable(build_candidate_recommendation)


def test_adaptation_proposal_rejects_future_belief_revision(tmp_path) -> None:
    as_of = datetime(2026, 1, 15, tzinfo=UTC)
    index = AdaptiveEvidenceIndex(tmp_path / "adaptive-evidence.sqlite")
    payload = {"verification_package_id": "verification-1"}
    receipt_payload = {"receipt_id": "receipt-1", "observed_at": as_of.isoformat()}
    index.append(
        AdaptiveEvidenceRecord(
            evidence_id="verification-1",
            record_kind="verification",
            payload=payload,
            payload_content_hash=canonical_sha256(payload),
            receipt_id="receipt-1",
            receipt_payload=receipt_payload,
            receipt_content_hash=canonical_sha256(receipt_payload),
            observed_at=as_of,
        ).sealed()
    )
    future = datetime(2026, 1, 16, tzinfo=UTC)
    prior = BeliefRevision(
        revision_id="r1",
        belief_id="b1",
        sequence=1,
        as_of=future,
        prior_probability=0.4,
        posterior_probability=0.4,
        assumption_ids=("a1",),
    ).sealed()
    proposed = BeliefRevision(
        revision_id="r2",
        belief_id="b1",
        sequence=2,
        as_of=future,
        prior_probability=0.4,
        posterior_probability=0.5,
        evidence_ids=("verification-1",),
        assumption_ids=("a1",),
        parent_revision_hash=prior.content_hash,
    ).sealed()

    with pytest.raises(ValueError, match="belief revisions must not be after proposal cutoff"):
        build_belief_adaptation_proposal(
            proposal_id="p1",
            index=index,
            as_of=as_of,
            envelope=AdaptiveTargetEnvelope(
                target_id="t1",
                basis_revision_hash=prior.content_hash,
                origin_receipt_id="o1",
                origin_receipt_hash="b" * 64,
                declared_origin_label="one",
                revision_proposer_label="two",
                version=1,
            ).sealed(),
            prior=prior,
            proposed=proposed,
            policy=AdaptationPolicy(
                policy_id="policy", as_of=as_of, max_probability_delta=0.2, policy_deadline=as_of
            ).sealed(),
        )
