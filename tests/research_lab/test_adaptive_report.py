from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from aegis.causal.beliefs import BeliefRevision
from aegis.contracts import canonical_sha256
from aegis.research_lab.adaptation import (
    AdaptationPolicy,
    AdaptiveEvaluationManifest,
    AdaptiveLoopPolicy,
    AdaptiveTargetEnvelope,
    build_adaptive_history,
    build_belief_adaptation_proposal,
    build_candidate_recommendation,
    evaluate_registered_adaptive_fixture,
)
from aegis.research_lab.adaptive_evidence import AdaptiveEvidenceIndex, AdaptiveEvidenceRecord
from aegis.research_lab.adaptive_report import AdaptiveReport, load_validated_adaptive_report
from apps.cli import app


def _sealed_report(tmp_path, *, evidence_id: str = "verification-1"):
    as_of = datetime(2026, 1, 15, tzinfo=UTC)
    index_path = tmp_path / "adaptive.sqlite"
    index = AdaptiveEvidenceIndex(index_path)
    payload = {"verification_package_id": "verification-1"}
    receipt = {"receipt_id": "receipt-1", "observed_at": as_of.isoformat()}
    index.append(
        AdaptiveEvidenceRecord(
            evidence_id=evidence_id,
            record_kind="verification",
            payload=payload,
            payload_content_hash=canonical_sha256(payload),
            receipt_id="receipt-1",
            receipt_payload=receipt,
            receipt_content_hash=canonical_sha256(receipt),
            observed_at=as_of,
        ).sealed()
    )
    prior = BeliefRevision(
        revision_id="r1",
        belief_id="b1",
        sequence=1,
        as_of=as_of,
        prior_probability=0.4,
        posterior_probability=0.4,
        assumption_ids=("a1",),
    ).sealed()
    proposed = BeliefRevision(
        revision_id="r2",
        belief_id="b1",
        sequence=2,
        as_of=as_of,
        prior_probability=0.4,
        posterior_probability=0.5,
        evidence_ids=(evidence_id,),
        assumption_ids=("a1",),
        parent_revision_hash=prior.content_hash,
    ).sealed()
    proposal = build_belief_adaptation_proposal(
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
    result = evaluate_registered_adaptive_fixture(
        AdaptiveEvaluationManifest(
            manifest_id="m1",
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
        recommendation_id="rec1", index=index, as_of=as_of, result=result
    )
    history = build_adaptive_history(
        policy=AdaptiveLoopPolicy(
            policy_id="loop",
            as_of=as_of,
            max_iterations=1,
            budget_units=2,
            deadline_reached=False,
            decision_robust=False,
            uncertainty_can_change_decision=True,
        ).sealed(),
        recommendations=(recommendation,),
        iteration_cost_units=(1,),
        expected_voi_units=(1,),
    )
    report = AdaptiveReport(
        report_id="report-1", history=history, evidence_checkpoint=index.checkpoint(as_of)
    ).sealed()
    report_path = tmp_path / "report.json"
    report_path.write_text(report.model_dump_json())
    return report, report_path, index_path


def test_adaptive_report_loader_requires_a_validated_index_context(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_validated_adaptive_report(
            tmp_path / "missing.json", index_path=tmp_path / "missing.sqlite"
        )


def test_adaptive_view_requires_its_index_and_rejects_action_flags(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    runner = CliRunner()
    assert runner.invoke(app, ["science", "adaptive-view", str(missing)]).exit_code != 0
    for flag in ("--create", "--run", "--approve", "--promote", "--acquire", "--write"):
        result = runner.invoke(app, ["science", "adaptive-view", str(missing), flag])
        assert result.exit_code != 0
        assert "No such option" in result.output


def test_adaptive_report_loads_only_when_sealed_and_index_bound(tmp_path) -> None:
    report, report_path, index_path = _sealed_report(tmp_path)
    assert load_validated_adaptive_report(report_path, index_path=index_path) == report
    unsealed = report.model_dump(mode="json", exclude={"content_hash"})
    report_path.write_text(json.dumps(unsealed))
    with pytest.raises(ValueError, match="must be sealed"):
        load_validated_adaptive_report(report_path, index_path=index_path)


def test_adaptive_report_rejects_fully_sealed_cross_index_history(tmp_path) -> None:
    report, report_path, index_path = _sealed_report(tmp_path)
    alternative_dir = tmp_path / "alternative"
    alternative_dir.mkdir()
    alternative, _, _ = _sealed_report(alternative_dir, evidence_id="verification-2")
    substituted = AdaptiveReport(
        report_id="cross-index",
        history=alternative.history,
        evidence_checkpoint=report.evidence_checkpoint,
    ).sealed()
    report_path.write_text(substituted.model_dump_json())

    with pytest.raises(ValueError, match="nested evidence index"):
        load_validated_adaptive_report(report_path, index_path=index_path)


def test_adaptive_report_rejects_substituted_proposal_checkpoint_after_recommendation_check(
    tmp_path, monkeypatch
) -> None:
    _, report_path, index_path = _sealed_report(tmp_path)
    from aegis.research_lab import adaptive_report

    original = adaptive_report.AdaptiveEvidenceIndex.checkpoint
    calls = 0

    def checkpoint_with_proposal_substitution(self, as_of):
        nonlocal calls
        calls += 1
        checkpoint = original(self, as_of)
        if calls == 3:
            payload = checkpoint.model_dump(mode="json", exclude={"content_hash"})
            payload["commitment_hash"] = "f" * 64
            return type(checkpoint).model_validate(payload).sealed()
        return checkpoint

    monkeypatch.setattr(
        adaptive_report.AdaptiveEvidenceIndex, "checkpoint", checkpoint_with_proposal_substitution
    )
    with pytest.raises(ValueError, match="nested evidence index"):
        load_validated_adaptive_report(report_path, index_path=index_path)
    assert calls == 3


def test_adaptive_view_is_byte_stable_and_read_only(tmp_path) -> None:
    _, report_path, index_path = _sealed_report(tmp_path)
    report_before = report_path.read_bytes()
    index_before = index_path.read_bytes()
    command = ["science", "adaptive-view", str(report_path), "--evidence-index", str(index_path)]
    first = CliRunner().invoke(app, command)
    second = CliRunner().invoke(app, command)

    assert first.exit_code == 0, first.output
    assert first.stdout.encode() == second.stdout.encode()
    assert json.loads(first.stdout)["status"]["authority"] == "candidate_only"
    assert report_path.read_bytes() == report_before
    assert index_path.read_bytes() == index_before
