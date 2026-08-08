from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aegis.contracts import (
    CandidatePatchMetadata,
    HoldoutUnlock,
    HypothesisDeclaration,
    LearningCandidate,
    OutcomeRecord,
    ShadowResult,
    canonical_sha256,
)
from aegis.research_lab.boundaries import CandidateBoundaryError, validate_candidate_target
from aegis.research_lab.builders import (
    build_experiment,
    build_promotion_decision,
    build_validation_report,
)
from aegis.research_lab.experiments import ExperimentIntegrityError, ExperimentLedger
from aegis.research_lab.outcomes import OutcomeIntegrityError, OutcomeLedger, build_postmortem
from aegis.research_lab.promotion import PromotionDenied, authorize_promotion
from aegis.research_lab.purgedcv_adapter import PurgedCVAdapter
from aegis.research_lab.static_checks import BuiltInQuantChecker, QTypeAdapter
from aegis.research_lab.validation import (
    ValidationPipeline,
    combinatorial_purged_splits,
    probability_of_backtest_overfitting,
    purged_walk_forward,
    validation_statistics,
)

NOW = datetime(2026, 8, 8, tzinfo=UTC)


def learning_candidate() -> LearningCandidate:
    return LearningCandidate(
        candidate_id="candidate-skill-1",
        candidate_type="skill",
        target_id="quant-signal-analysis",
        proposed_patch="Tighten the point-in-time precondition.",
        trigger_case_ids=["case-1"],
        evidence_ids=["evidence-1"],
        diagnosis="A precondition was underspecified.",
        expected_improvement="Fewer leakage defects.",
        falsifiable_metric="zero future-timestamp acceptance failures",
        minimum_required_delta=0.01,
        risk_class="high",
        evaluation_suite_id="suite-v1",
        proposer_model="replay-model",
        proposer_id="postmortem-agent",
        status="shadow",
    )


def test_candidate_boundaries_reject_locked_traversal_and_symlinks(tmp_path: Path) -> None:
    allowed = validate_candidate_target(tmp_path, "skills/candidates/new/SKILL.md")
    assert allowed.is_relative_to(tmp_path)
    for target in ("aegis/fund/run_cycle.py", "../escape", "/tmp/escape"):
        with pytest.raises(CandidateBoundaryError):
            validate_candidate_target(tmp_path, target)
    (tmp_path / "skills").mkdir(exist_ok=True)
    (tmp_path / "skills/candidates").symlink_to(tmp_path / "outside")
    with pytest.raises(CandidateBoundaryError):
        validate_candidate_target(tmp_path, "skills/candidates/x/SKILL.md")


def test_static_time_leak_checker_blocks_negative_shift() -> None:
    diagnostics = BuiltInQuantChecker.check("signal = prices.shift(-1)\n")
    assert [item.rule_id for item in diagnostics] == ["AQ001"]
    assert BuiltInQuantChecker.check("signal = prices.shift(1)\n") == ()


def test_purged_splits_statistics_and_preflight_order() -> None:
    folds = purged_walk_forward(60, 3, minimum_train=24, purge=2, embargo=1)
    assert len(folds) == 3
    assert all(
        not set(train).intersection(test) and max(train) <= min(test) - 3 for train, test in folds
    )
    cpcv = combinatorial_purged_splits(60, 6, 2, embargo_groups=1)
    assert len(cpcv) == 15
    assert all(not set(train).intersection(test) for train, test in cpcv)
    stats = validation_statistics(
        [0.01, -0.003, 0.008, 0.002, -0.001, 0.006],
        trial_sharpes=[0.2, 0.4, 0.1],
    )
    assert 0 <= stats["probabilistic_sharpe_ratio"] <= 1
    assert 0 <= stats["deflated_sharpe_ratio"] <= 1
    pbo = probability_of_backtest_overfitting([[1, 2, 3, 4], [4, 3, 2, 1], [2, 2, 2, 2]])
    assert 0 <= pbo <= 1
    calls = []
    result = ValidationPipeline().run(
        {
            "preflight": lambda: False,
            "historical_dev": lambda: calls.append("backtest") or True,
        }
    )
    assert result == {"preflight": False}
    assert calls == []


def test_experiment_ledger_is_append_only_and_tamper_detecting(tmp_path: Path) -> None:
    hypothesis = HypothesisDeclaration(
        hypothesis_id="hypothesis-1",
        candidate_id="candidate-skill-1",
        statement="The patch reduces leakage failures.",
        primary_metric="leakage_failure_rate",
        minimum_delta=0.01,
        baseline_id="baseline-v1",
        declared_at=NOW,
        declared_by="researcher",
    )
    record = build_experiment(
        experiment_id="experiment-1",
        candidate_id=hypothesis.candidate_id,
        hypothesis_id=hypothesis.hypothesis_id,
        code_revision="abc123",
        tree_hash="a" * 64,
        data_snapshot_hash="b" * 64,
        trial_number=1,
        status="declared",
        created_at=NOW,
    )
    ledger = ExperimentLedger(tmp_path / "experiments.sqlite")
    ledger.append(record)
    ledger.append(record)
    assert ledger.get(record.experiment_id) == record
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            "UPDATE experiments SET record_hash = ? WHERE experiment_id = ?",
            ("0" * 64, record.experiment_id),
        )
    with pytest.raises(ExperimentIntegrityError):
        ledger.get(record.experiment_id)


def test_promotion_requires_independent_validation_and_human_hash_binding(
    tmp_path: Path,
) -> None:
    candidate = learning_candidate()
    candidate_hash = canonical_sha256(candidate)
    report = build_validation_report(
        report_id="report-1",
        candidate_id=candidate.candidate_id,
        candidate_hash=candidate_hash,
        evaluator_id="independent-evaluator",
        stages=[
            "preflight",
            "replay",
            "historical_dev",
            "holdback",
            "purged_cv",
            "overfitting",
            "cost_stress",
            "shadow",
        ],
        stage_passes={
            stage: True
            for stage in [
                "preflight",
                "replay",
                "historical_dev",
                "holdback",
                "purged_cv",
                "overfitting",
                "cost_stress",
                "shadow",
            ]
        },
        metrics={
            "pbo": 0.1,
            "psr": 0.97,
            "dsr": 0.95,
            "turnover": 0.2,
            "capacity": 1_000_000.0,
            "costs": 250.0,
            "max_drawdown": -0.08,
        },
        baseline_metrics={"dsr": 0.7},
        ablation_metrics={"dsr": 0.4},
        trial_count=3,
        holdout_unlock_id="human-holdout-unlock-1",
        passed=True,
        evaluated_at=NOW,
    )
    patch = CandidatePatchMetadata(
        candidate_id=candidate.candidate_id,
        target_path="skills/candidates/quant-signal.md",
        base_revision="abc123",
        base_tree_hash="1" * 64,
        patch_hash=canonical_sha256(candidate.proposed_patch),
        candidate_tree_hash="2" * 64,
    )
    unlock_values = dict(
        unlock_id="human-holdout-unlock-1",
        suite_id=candidate.evaluation_suite_id,
        human_approver_id="holdout-owner",
        reason="Independent unlock after candidate declaration.",
        unlocked_at=NOW,
    )
    holdout_unlock = HoldoutUnlock(**unlock_values, content_hash=canonical_sha256(unlock_values))
    shadow_values = dict(
        shadow_id="shadow-1",
        candidate_id=candidate.candidate_id,
        baseline_run_ids=["baseline-run"],
        candidate_run_ids=["candidate-run"],
        metrics={"excess_return": 0.01},
        passed=True,
        completed_at=NOW,
    )
    shadow_result = ShadowResult(**shadow_values, content_hash=canonical_sha256(shadow_values))
    decision = build_promotion_decision(
        promotion_id="promotion-1",
        candidate_id=candidate.candidate_id,
        candidate_hash=candidate_hash,
        validation_report_id=report.report_id,
        validation_report_hash=report.content_hash,
        patch_metadata_hash=canonical_sha256(patch),
        holdout_unlock_id=holdout_unlock.unlock_id,
        holdout_unlock_hash=holdout_unlock.content_hash,
        shadow_result_id=shadow_result.shadow_id,
        shadow_result_hash=shadow_result.content_hash,
        evaluator_id=report.evaluator_id,
        human_approver_id="human-owner",
        decision="promote",
        reason="All locked gates passed.",
        decided_at=NOW.replace(minute=1),
    )
    assert authorize_promotion(
        candidate,
        report,
        decision,
        patch=patch,
        holdout_unlock=holdout_unlock,
        shadow_result=shadow_result,
        project_root=tmp_path,
    )
    self_approved = build_promotion_decision(
        **{
            **decision.model_dump(exclude={"content_hash"}),
            "promotion_id": "promotion-self",
            "human_approver_id": candidate.proposer_id,
        }
    )
    with pytest.raises(PromotionDenied, match="independent"):
        authorize_promotion(
            candidate,
            report,
            self_approved,
            patch=patch,
            holdout_unlock=holdout_unlock,
            shadow_result=shadow_result,
            project_root=tmp_path,
        )

    rejected = candidate.model_copy(update={"status": "rejected"})
    with pytest.raises(PromotionDenied, match="shadow status"):
        authorize_promotion(
            rejected,
            report,
            decision,
            patch=patch,
            holdout_unlock=holdout_unlock,
            shadow_result=shadow_result,
            project_root=tmp_path,
        )
    same_evaluator = build_promotion_decision(
        **{
            **decision.model_dump(exclude={"content_hash"}),
            "promotion_id": "promotion-evaluator-self",
            "human_approver_id": report.evaluator_id,
        }
    )
    with pytest.raises(PromotionDenied, match="independent"):
        authorize_promotion(
            candidate,
            report,
            same_evaluator,
            patch=patch,
            holdout_unlock=holdout_unlock,
            shadow_result=shadow_result,
            project_root=tmp_path,
        )
    early_decision = build_promotion_decision(
        **{
            **decision.model_dump(exclude={"content_hash"}),
            "promotion_id": "promotion-too-early",
            "decided_at": NOW - timedelta(days=1),
        }
    )
    with pytest.raises(PromotionDenied, match="follow completed evaluation"):
        authorize_promotion(
            candidate,
            report,
            early_decision,
            patch=patch,
            holdout_unlock=holdout_unlock,
            shadow_result=shadow_result,
            project_root=tmp_path,
        )
    disconnected_patch = patch.model_copy(update={"patch_hash": "3" * 64})
    with pytest.raises(PromotionDenied, match="patch metadata"):
        authorize_promotion(
            candidate,
            report,
            decision,
            patch=disconnected_patch,
            holdout_unlock=holdout_unlock,
            shadow_result=shadow_result,
            project_root=tmp_path,
        )


def test_pinned_qtype_and_purgedcv_optional_adapters(tmp_path: Path) -> None:
    source = tmp_path / "candidate.py"
    source.write_text("signal = prices.shift(-1)\n")
    diagnostics = QTypeAdapter(required=True).check(source)
    assert any(item.rule_id == "QT001" for item in diagnostics)
    adapter = PurgedCVAdapter()
    assert adapter.available()
    library_splits = adapter.build_library_splits(40, n_splits=4, purge_days=1, embargo_days=1)
    assert len(library_splits) == 4
    assert all(not set(train).intersection(test) for train, test in library_splits)
    adapter.validate_indices([((0, 1), (3, 4))], locked_holdout={5, 6})
    with pytest.raises(ValueError, match="locked final holdout"):
        adapter.validate_indices([((0, 5), (3, 4))], locked_holdout={5, 6})


def test_matured_outcome_postmortem_is_append_only_and_candidate_only(tmp_path: Path) -> None:
    outcome = OutcomeRecord(
        outcome_id="outcome-1",
        case_id="case-1",
        forecast_id="forecast-1",
        ticker="NVDA",
        horizon_end=NOW,
        realized_excess_return=0.02,
        forecast_error=-0.01,
        costs=2.5,
        available_at=NOW + timedelta(hours=1),
    )
    ledger = OutcomeLedger(tmp_path / "outcomes.sqlite")
    ledger.append_outcome(outcome)
    report = build_postmortem(
        "postmortem-1",
        [outcome],
        NOW + timedelta(hours=2),
        candidate_ids=["candidate-skill-1"],
    )
    ledger.append_postmortem(report)
    assert ledger.outcomes() == (outcome,)
    assert report.candidate_ids == ["candidate-skill-1"]
    with sqlite3.connect(ledger.path) as connection:
        connection.execute("UPDATE outcomes SET payload = replace(payload, '0.02', '0.20')")
    with pytest.raises(OutcomeIntegrityError, match="tampering"):
        ledger.outcomes()
    immature = outcome.model_copy(
        update={"outcome_id": "immature", "available_at": NOW - timedelta(seconds=1)}
    )
    with pytest.raises(OutcomeIntegrityError, match="not mature"):
        ledger.append_outcome(immature)
