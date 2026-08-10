from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from aegis.contracts import ExperimentRecord, canonical_json, canonical_sha256
from aegis.harness.capability_broker import CapabilityDenied
from aegis.reporting.traceability import SnapshotReference, SourceProvenanceReference
from aegis.research_lab.experiments import ExperimentIntegrityError, ExperimentLedger
from aegis.research_lab.science import (
    ExperimentPlan,
    ExperimentRun,
    ExperimentRunAbstention,
    Hypothesis,
    HypothesisFamily,
    NegativeResult,
    NoveltyReport,
    ReplicationRun,
    ResearchArchive,
    ResearchArtifactReceiptReference,
    ResearchBudget,
    ResearchClaim,
    ResearchContribution,
    ResearchContributionReport,
    ResearchCritiqueReceipt,
    ResearchEvidenceBinding,
    ResearchPortfolio,
    ResearchPortfolioCandidate,
    ResearchPostmortem,
    ResearchProgramme,
    ResearchTeam,
    ResearchTree,
    ResearchTreeNode,
    ScienceReport,
    VerificationPackage,
    _experiment_record,
    authorize_v6_research_tool,
    evaluate_registered_fixture,
    load_experiment_run,
    rank_research_portfolio,
    record_experiment_run,
    science_report_view,
)

AS_OF = datetime(2026, 1, 15, tzinfo=UTC)
LOCKED_FIELDS = (
    "dataset_snapshot_hash",
    "split_policy_id",
    "metric_ids",
    "baseline_ids",
    "ablation_ids",
    "cost_model_id",
    "stop_rules",
)


def _evidence_binding(
    *,
    as_of: datetime = AS_OF,
    source_available_at: datetime | None = None,
    retained_hash: str | None = None,
) -> ResearchEvidenceBinding:
    source_available_at = source_available_at or as_of - timedelta(days=1)
    sources = (
        SourceProvenanceReference(
            source_id="source-1",
            artifact_id="source-artifact-1",
            content_hash="a" * 64,
            available_at=source_available_at,
        ),
    )
    snapshot = SnapshotReference(
        snapshot_id="snapshot-1",
        content_hash="b" * 64,
        as_of=as_of,
    )
    artifact_hash = canonical_sha256(
        {
            "as_of": as_of,
            "source_provenance": sources,
            "snapshot": snapshot,
        }
    )
    receipt = ResearchArtifactReceiptReference(
        receipt_id="receipt-1",
        artifact_id="evidence-binding-1",
        artifact_content_hash=retained_hash or artifact_hash,
        recorded_at=as_of + timedelta(minutes=1),
    ).sealed()
    return ResearchEvidenceBinding(
        binding_id="evidence-binding-1",
        as_of=as_of,
        source_provenance=sources,
        snapshot=snapshot,
        original_receipt=receipt,
    ).sealed()


def _hypothesis(
    hypothesis_id: str,
    mechanism_id: str,
    competitor_id: str,
    evidence_binding: ResearchEvidenceBinding,
    programme_id: str = "programme-1",
) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=hypothesis_id,
        programme_id=programme_id,
        mechanism_id=mechanism_id,
        statement=f"Candidate statement for {mechanism_id}.",
        falsifiable_predictions=(f"prediction-{hypothesis_id}",),
        assumption_ids=(f"assumption-{hypothesis_id}",),
        known_failure_condition=f"failure-{hypothesis_id}",
        competes_with=(competitor_id,),
        proposer_id="hypothesis-architect-1",
        evidence_binding=evidence_binding,
    ).sealed()


def _programme(*, max_tree_depth: int = 2, programme_id: str = "programme-1") -> ResearchProgramme:
    binding = _evidence_binding()
    first = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", binding, programme_id)
    second = _hypothesis("hypothesis-b", "mechanism-b", "hypothesis-a", binding, programme_id)
    family = HypothesisFamily(
        family_id="family-1",
        programme_id=programme_id,
        hypotheses=(first, second),
    ).sealed()
    budget = ResearchBudget(
        compute_limit=10.0,
        data_limit=5.0,
        review_limit=3.0,
        total_limit=18.0,
    ).sealed()
    return ResearchProgramme(
        programme_id=programme_id,
        mandate="Test competing candidate mechanisms.",
        as_of=AS_OF,
        owner_id="research-director-1",
        expected_decision_value=1.0,
        budget=budget,
        max_team_count=3,
        max_tree_depth=max_tree_depth,
        hypothesis_families=(family,),
        evidence_binding=binding,
    ).sealed()


def _reviewed_tree_and_plan() -> tuple[ResearchTree, ExperimentPlan]:
    programme = _programme()
    hypothesis = programme.hypothesis_families[0].hypotheses[0]
    team = ResearchTeam(
        team_id="team-ledger",
        programme_id=programme.programme_id,
        role="experiment_designer",
        member_ids=("designer-ledger",),
        compute_limit=10.0,
    ).sealed()
    critique = ResearchCritiqueReceipt(
        critique_id="critique-ledger",
        node_id="node-ledger",
        reviewer_id="reviewer-ledger",
        recorded_at=AS_OF + timedelta(seconds=90),
        findings=("Fixture evaluation is bounded.",),
        evidence_binding=programme.evidence_binding,
    ).sealed()
    node = ResearchTreeNode(
        node_id="node-ledger",
        programme_id=programme.programme_id,
        team_id=team.team_id,
        hypothesis_id=hypothesis.hypothesis_id,
        depth=0,
        compute_cost=1.0,
        critique=critique,
    ).sealed()
    tree = ResearchTree(
        tree_id="tree-ledger",
        programme=programme,
        teams=(team,),
        nodes=(node,),
    ).sealed()
    plan = ExperimentPlan(
        experiment_id="experiment-ledger",
        tree_node_id=node.node_id,
        hypothesis=hypothesis,
        preregistered_at=AS_OF + timedelta(minutes=2),
        evidence_binding=programme.evidence_binding,
        dataset_snapshot_hash=programme.evidence_binding.snapshot.content_hash,
        split_policy_id="split-policy-1",
        metric_ids=("metric-1",),
        baseline_ids=("baseline-1",),
        ablation_ids=("ablation-1",),
        cost_model_id="cost-model-1",
        stop_rules=("stop-rule-1",),
        locked_fields=LOCKED_FIELDS,
        author_id="designer-ledger",
    ).sealed()
    return tree, plan


def _experiment_run(tree: ResearchTree, plan: ExperimentPlan) -> ExperimentRun:
    draft = ExperimentRun(
        experiment_id=plan.experiment_id,
        programme_id=tree.programme.programme_id,
        plan=plan,
        executor_id="registered-fixture-1",
        code_revision="aa78abd",
        tree_hash=tree.content_hash,
        data_snapshot_hash=plan.dataset_snapshot_hash,
        seed=7,
        parameter_draw_hash="c" * 64,
        result_content_hash="d" * 64,
        trial_number=1,
        status="passed",
        started_at=AS_OF + timedelta(minutes=3),
        completed_at=AS_OF + timedelta(minutes=4),
    ).sealed()
    return _with_fixture_outcome(draft)


def _with_fixture_outcome(run: ExperimentRun) -> ExperimentRun:
    status, result_hash = evaluate_registered_fixture(run)
    return run.model_copy(
        update={"status": status, "result_content_hash": result_hash, "content_hash": None}
    ).sealed()


def test_experiment_plan_denies_candidate_selected_locked_values() -> None:
    _, plan = _reviewed_tree_and_plan()

    for update in (
        {"split_policy_id": "candidate-split"},
        {"metric_ids": ("candidate-metric",)},
        {"cost_model_id": "candidate-cost"},
    ):
        with pytest.raises(ValidationError, match="governed fixture evaluation policy"):
            plan.model_copy(update=update | {"content_hash": None})


def test_completed_run_is_persisted_before_return(tmp_path: Path) -> None:
    tree, plan = _reviewed_tree_and_plan()
    run = _experiment_run(tree, plan)
    ledger = ExperimentLedger(tmp_path / "v6-experiments.sqlite")

    returned = record_experiment_run(ledger, run, tree)
    record = ledger.get(run.experiment_id)
    assert returned == run
    assert record.parameters["v6_run_content_hash"] == run.content_hash
    assert load_experiment_run(record) == run

    before = hashlib.sha256(ledger.path.read_bytes()).hexdigest()
    read_only = ExperimentLedger(ledger.path, read_only=True)
    assert read_only.get(run.experiment_id) == record
    with pytest.raises(ExperimentIntegrityError, match="read-only"):
        read_only.append(record)
    assert hashlib.sha256(ledger.path.read_bytes()).hexdigest() == before
    with pytest.raises(FileNotFoundError):
        ExperimentLedger(tmp_path / "missing-read-only.sqlite", read_only=True)


def test_registered_fixture_recomputes_outcome_before_ledger_write(tmp_path: Path) -> None:
    tree, plan = _reviewed_tree_and_plan()
    run = _experiment_run(tree, plan)
    assert evaluate_registered_fixture(run) == (run.status, run.result_content_hash)
    forged = run.model_copy(
        update={
            "status": "failed",
            "result_content_hash": "e" * 64,
            "content_hash": None,
        }
    ).sealed()
    ledger = ExperimentLedger(tmp_path / "forged-fixture-outcome.sqlite")

    with pytest.raises(ValueError, match="deterministic registered-fixture outcome"):
        record_experiment_run(ledger, forged, tree)
    with pytest.raises(KeyError):
        ledger.get(forged.experiment_id)
    with pytest.raises(ExperimentIntegrityError, match="deterministic registered-fixture outcome"):
        ledger.append(_experiment_record(forged))


def test_experiment_run_rejects_unpersisted_return_and_nested_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree, plan = _reviewed_tree_and_plan()
    run = _experiment_run(tree, plan)
    rejected_ledger = ExperimentLedger(tmp_path / "rejected.sqlite")

    def reject_append(_record: ExperimentRecord) -> None:
        raise RuntimeError("persistence unavailable")

    monkeypatch.setattr(rejected_ledger, "append", reject_append)
    with pytest.raises(RuntimeError, match="persistence unavailable"):
        record_experiment_run(rejected_ledger, run, tree)
    with pytest.raises(KeyError):
        rejected_ledger.get(run.experiment_id)

    ledger = ExperimentLedger(tmp_path / "tampered.sqlite")
    record_experiment_run(ledger, run, tree)
    record = ledger.get(run.experiment_id)
    payload = record.model_dump(exclude={"content_hash"})
    payload["parameters"] = record.parameters | {"v6_run_content_hash": "f" * 64}
    forged = ExperimentRecord(**payload, content_hash=canonical_sha256(payload))
    with pytest.raises(ValueError, match="v6 run content hash mismatch"):
        load_experiment_run(forged)

    outer_payload = record.model_dump(exclude={"content_hash"}) | {"code_revision": "forged"}
    forged_outer = ExperimentRecord(**outer_payload, content_hash=canonical_sha256(outer_payload))
    with pytest.raises(ValueError, match="envelope does not match"):
        load_experiment_run(forged_outer)

    with pytest.raises(ValidationError, match="ID must match"):
        run.model_copy(update={"experiment_id": "other", "content_hash": None})
    with pytest.raises(ValidationError, match="data snapshot"):
        run.model_copy(update={"data_snapshot_hash": "e" * 64, "content_hash": None})
    with pytest.raises(ValidationError, match="start after preregistration"):
        run.model_copy(update={"started_at": plan.preregistered_at, "content_hash": None})
    with pytest.raises(ValidationError, match="completion"):
        run.model_copy(
            update={
                "completed_at": run.started_at - timedelta(seconds=1),
                "content_hash": None,
            }
        )
    wrong_tree_run = run.model_copy(update={"tree_hash": "e" * 64, "content_hash": None}).sealed()
    with pytest.raises(ValueError, match="does not match its research tree"):
        record_experiment_run(
            ExperimentLedger(tmp_path / "wrong-tree.sqlite"), wrong_tree_run, tree
        )

    assert record_experiment_run(ledger, run, tree) == run
    changed_run = run.model_copy(
        update={"result_content_hash": "e" * 64, "content_hash": None}
    ).sealed()
    with pytest.raises(ValueError, match="deterministic registered-fixture outcome"):
        record_experiment_run(ledger, changed_run, tree)


def test_unknown_fixture_executor_abstains_without_ledger_record(tmp_path: Path) -> None:
    tree, plan = _reviewed_tree_and_plan()
    run = (
        _experiment_run(tree, plan)
        .model_copy(update={"executor_id": "unknown-fixture", "content_hash": None})
        .sealed()
    )
    ledger = ExperimentLedger(tmp_path / "unknown-executor.sqlite")

    result = record_experiment_run(ledger, run, tree)
    assert isinstance(result, ExperimentRunAbstention)
    assert result.reason == "unsupported_or_unavailable_executor"
    with pytest.raises(KeyError):
        ledger.get(run.experiment_id)

    malformed_plan = plan.model_copy(
        update={"tree_node_id": "missing-node", "content_hash": None}
    ).sealed()
    malformed_run = run.model_copy(update={"plan": malformed_plan, "content_hash": None}).sealed()
    with pytest.raises(ValueError, match="tree node hypothesis"):
        record_experiment_run(ledger, malformed_run, tree)


def test_verified_claim_requires_independent_replication_and_identities(tmp_path: Path) -> None:
    tree, plan = _reviewed_tree_and_plan()
    original = _experiment_run(tree, plan)
    replication_plan = plan.model_copy(
        update={
            "experiment_id": "experiment-replication",
            "author_id": "replicator-1",
            "content_hash": None,
        }
    ).sealed()
    replication_run = _with_fixture_outcome(
        _experiment_run(tree, replication_plan).model_copy(
            update={"seed": 11, "content_hash": None}
        )
    )
    ledger = ExperimentLedger(tmp_path / "verification.sqlite")
    assert record_experiment_run(ledger, original, tree) == original
    assert record_experiment_run(ledger, replication_run, tree) == replication_run
    original_record = ledger.get(original.experiment_id)
    replication_record = ledger.get(replication_run.experiment_id)
    replication = ReplicationRun(
        replication_id="replication-1",
        original_run=original,
        original_record=original_record,
        replication_run=replication_run,
        replication_record=replication_record,
        replicator_id="replicator-1",
        recorded_at=AS_OF + timedelta(minutes=5),
    ).sealed()
    package = VerificationPackage(
        package_id="verification-1",
        original_run=original,
        original_record=original_record,
        replications=(replication,),
        verifier_id="verifier-1",
        approver_id="approver-1",
        limitations=("Registered fixture evidence only.",),
        claim_strength_ceiling="verified",
        verified_at=AS_OF + timedelta(minutes=6),
    ).sealed()
    with pytest.raises(ValidationError, match="ledger verification context"):
        ResearchClaim(
            claim_id="claim-unledgered",
            package=package,
            status="verified",
            conclusion="Unverified direct construction.",
        )
    claim = ResearchClaim.verified(
        claim_id="claim-1",
        package=package,
        conclusion="The registered fixture reproduced the bounded result.",
        ledger=ledger,
    )
    assert claim.authority == "candidate_only"

    report_archive = ResearchArchive(
        archive_id="archive-verified-report",
        programme_id=tree.programme.programme_id,
    ).sealed()
    report_payload = {
        "report_id": "report-verified",
        "programme": tree.programme,
        "archive": report_archive,
        "verification_package": package,
        "declared_strength": package.claim_strength_ceiling,
        "declared_limitations": package.limitations,
    }
    with pytest.raises(ValidationError, match="ledger verification context"):
        ScienceReport(**report_payload)
    read_only_ledger = ExperimentLedger(ledger.path, read_only=True)
    verified_report = ScienceReport.verified(
        report_id="report-verified",
        programme=tree.programme,
        archive=report_archive,
        verification_package=package,
        ledger=read_only_ledger,
    )
    with pytest.raises(ValidationError, match="ledger verification context"):
        science_report_view(verified_report)
    assert science_report_view(verified_report, ledger=read_only_ledger)["verification"] == {
        "claim_strength": "verified",
        "limitations": ["Registered fixture evidence only."],
        "package_id": "verification-1",
        "replication_ids": ["replication-1"],
    }
    with pytest.raises(KeyError):
        ResearchClaim.verified(
            claim_id="claim-missing-ledger",
            package=package,
            conclusion="Must not verify without ledger inclusion.",
            ledger=ExperimentLedger(tmp_path / "empty-verification.sqlite"),
        )

    limited_package = package.model_copy(
        update={
            "replications": (),
            "claim_strength_ceiling": "limited",
            "content_hash": None,
        }
    ).sealed()
    limited = ResearchClaim(
        claim_id="claim-limited",
        package=limited_package,
        status="limited",
        conclusion="Limited registered-fixture observation only.",
    ).sealed()
    assert limited.status == "limited"
    with pytest.raises(ValidationError, match="verified replication support"):
        ResearchClaim(
            claim_id="claim-inflated",
            package=limited_package,
            status="verified",
            conclusion="Unsupported verified claim.",
        )
    with pytest.raises(ValidationError, match="verification package"):
        ResearchClaim(
            claim_id="claim-unbound",
            status="limited",
            conclusion="Unbound conclusion.",
        )
    with pytest.raises(ValidationError, match="cannot contain a conclusion"):
        ResearchClaim(
            claim_id="claim-abstained",
            status="abstained",
            conclusion="Should not exist.",
        )

    with pytest.raises(ValidationError, match="independent replicator"):
        ReplicationRun(
            replication_id="replication-self",
            original_run=original,
            original_record=original_record,
            replication_run=replication_run,
            replication_record=replication_record,
            replicator_id=original.plan.hypothesis.proposer_id,
            recorded_at=AS_OF + timedelta(minutes=5),
        )
    with pytest.raises(ValidationError, match="identity separation"):
        package.model_copy(update={"approver_id": package.verifier_id, "content_hash": None})
    with pytest.raises(ValidationError, match="replication"):
        VerificationPackage(
            package_id="verification-missing-replication",
            original_run=original,
            original_record=original_record,
            replications=(),
            verifier_id="verifier-1",
            approver_id="approver-1",
            limitations=("No replication.",),
            claim_strength_ceiling="verified",
            verified_at=AS_OF + timedelta(minutes=6),
        )
    failed_run = _with_fixture_outcome(
        replication_run.model_copy(
            update={"executor_id": "registered-fixture-failure-1", "content_hash": None}
        )
    )
    failed_ledger = ExperimentLedger(tmp_path / "failed-replication.sqlite")
    assert record_experiment_run(failed_ledger, failed_run, tree) == failed_run
    failed_replication = ReplicationRun(
        replication_id="replication-failed",
        original_run=original,
        original_record=original_record,
        replication_run=failed_run,
        replication_record=failed_ledger.get(failed_run.experiment_id),
        replicator_id="replicator-1",
        recorded_at=AS_OF + timedelta(minutes=5),
    ).sealed()
    with pytest.raises(ValidationError, match="passed supporting runs"):
        package.model_copy(update={"replications": (failed_replication,), "content_hash": None})
    duplicate_wrapper = replication.model_copy(
        update={"replication_id": "replication-duplicate", "content_hash": None}
    ).sealed()
    with pytest.raises(ValidationError, match="replication runs must be unique"):
        package.model_copy(
            update={"replications": (replication, duplicate_wrapper), "content_hash": None}
        )


def test_science_report_cannot_exceed_verification_package_and_is_byte_stable(
    tmp_path: Path,
) -> None:
    tree, plan = _reviewed_tree_and_plan()
    run = _experiment_run(tree, plan)
    ledger = ExperimentLedger(tmp_path / "science-report.sqlite")
    assert record_experiment_run(ledger, run, tree) == run
    package = VerificationPackage(
        package_id="verification-report",
        original_run=run,
        original_record=ledger.get(run.experiment_id),
        verifier_id="verifier-report",
        approver_id="approver-report",
        limitations=("Registered fixture evidence only.",),
        claim_strength_ceiling="limited",
        verified_at=AS_OF + timedelta(minutes=6),
    ).sealed()
    archive = ResearchArchive(
        archive_id="archive-report",
        programme_id=tree.programme.programme_id,
    ).sealed()

    with pytest.raises(ValidationError, match="verification strength"):
        ScienceReport(
            report_id="report-inflated",
            programme=tree.programme,
            archive=archive,
            verification_package=package,
            declared_strength="verified",
            declared_limitations=package.limitations,
        )

    report = ScienceReport(
        report_id="report-1",
        programme=tree.programme,
        archive=archive,
        verification_package=package,
        declared_strength=package.claim_strength_ceiling,
        declared_limitations=package.limitations,
    ).sealed()
    first = canonical_json(science_report_view(report))
    second = canonical_json(science_report_view(report))
    assert first.encode() == second.encode()
    assert science_report_view(report)["verification"] == {
        "claim_strength": "limited",
        "limitations": ["Registered fixture evidence only."],
        "package_id": "verification-report",
        "replication_ids": [],
    }

    alien_hypothesis = plan.hypothesis.model_copy(
        update={"statement": "Substituted hypothesis.", "content_hash": None}
    ).sealed()
    alien_plan = plan.model_copy(
        update={"hypothesis": alien_hypothesis, "content_hash": None}
    ).sealed()
    alien_run = run.model_copy(update={"plan": alien_plan, "content_hash": None}).sealed()
    alien_negative = NegativeResult(
        negative_result_id="negative-alien",
        run=alien_run,
        disposition="inconclusive",
        category="causal",
        reason="Substituted run.",
        reopen_condition="Never use this report lineage.",
        mechanism_id=alien_hypothesis.mechanism_id,
        assumption_ids=alien_hypothesis.assumption_ids,
        recorded_at=AS_OF + timedelta(minutes=5),
        evidence_binding=tree.programme.evidence_binding,
    ).sealed()
    alien_archive = ResearchArchive(
        archive_id="archive-alien",
        programme_id=tree.programme.programme_id,
        negative_results=(alien_negative,),
    ).sealed()
    with pytest.raises(ValidationError, match="lineage"):
        report.model_copy(update={"archive": alien_archive, "content_hash": None})

    alien_postmortem = ResearchPostmortem(
        postmortem_id="postmortem-alien",
        run=alien_run,
        outcome="inconclusive",
        negative_result=alien_negative,
        reviewer_id="reviewer-alien",
        limitations=("Substituted run.",),
        recorded_at=AS_OF + timedelta(minutes=6),
        evidence_binding=tree.programme.evidence_binding,
    ).sealed()
    with pytest.raises(ValidationError, match="lineage"):
        report.model_copy(update={"postmortems": (alien_postmortem,), "content_hash": None})


def test_archive_surfaces_prior_negative_results_and_reconciles_contributions() -> None:
    tree, plan = _reviewed_tree_and_plan()
    run = _experiment_run(tree, plan)
    hypothesis = plan.hypothesis
    negative = NegativeResult(
        negative_result_id="negative-1",
        run=run,
        disposition="inconclusive",
        category="causal",
        reason="The fixture cannot distinguish the competing mechanism.",
        reopen_condition="A governed independent snapshot becomes available.",
        mechanism_id=hypothesis.mechanism_id,
        assumption_ids=hypothesis.assumption_ids,
        recorded_at=AS_OF + timedelta(minutes=5),
        evidence_binding=tree.programme.evidence_binding,
    ).sealed()
    archive = ResearchArchive(
        archive_id="archive-1",
        programme_id=tree.programme.programme_id,
        negative_results=(negative,),
    ).sealed()
    assert archive.surfaced_negative_results(hypothesis) == (negative,)
    postmortem = ResearchPostmortem(
        postmortem_id="postmortem-1",
        run=run,
        outcome="inconclusive",
        negative_result=negative,
        reviewer_id="reviewer-1",
        limitations=("No external calibration evidence.",),
        recorded_at=AS_OF + timedelta(minutes=6),
        evidence_binding=tree.programme.evidence_binding,
    ).sealed()
    assert postmortem.release_disposition == "engineering_only"
    with pytest.raises(ValidationError, match="outcome must match"):
        ResearchPostmortem(
            postmortem_id="postmortem-mismatch",
            run=run,
            outcome="negative",
            negative_result=negative,
            reviewer_id="reviewer-1",
            limitations=("Mismatched disposition.",),
            recorded_at=AS_OF + timedelta(minutes=6),
            evidence_binding=tree.programme.evidence_binding,
        )
    failed_run = run.model_copy(update={"status": "failed", "content_hash": None}).sealed()
    with pytest.raises(ValidationError, match="positive postmortem requires a passed run"):
        ResearchPostmortem(
            postmortem_id="postmortem-failed-positive",
            run=failed_run,
            outcome="positive",
            reviewer_id="reviewer-1",
            limitations=("Failed run.",),
            recorded_at=AS_OF + timedelta(minutes=6),
            evidence_binding=tree.programme.evidence_binding,
        )

    report = NoveltyReport(
        novelty_report_id="novelty-archive",
        hypothesis=hypothesis,
        assessed_at=AS_OF + timedelta(minutes=6),
        evidence_binding=tree.programme.evidence_binding,
        surfaced_negative_result_ids=(),
        limitations=("Internal archive only.",),
        auditor_id="novelty-auditor-1",
    ).sealed()
    with pytest.raises(ValueError, match="surfaced negative results"):
        archive.validate_novelty_report(report)
    future_negative = negative.model_copy(
        update={"recorded_at": AS_OF + timedelta(minutes=7), "content_hash": None}
    ).sealed()
    future_archive = ResearchArchive(
        archive_id="archive-future",
        programme_id=tree.programme.programme_id,
        negative_results=(future_negative,),
    ).sealed()
    future_report = report.model_copy(
        update={
            "surfaced_negative_result_ids": (negative.negative_result_id,),
            "content_hash": None,
        }
    ).sealed()
    with pytest.raises(ValueError, match="prior negative results"):
        future_archive.validate_novelty_report(future_report)

    contributions = ResearchContributionReport(
        report_id="contributions-1",
        contributions=(
            ResearchContribution(mechanism_path="mechanism-a", amount=0.4).sealed(),
            ResearchContribution(mechanism_path="mechanism-b", amount=0.6).sealed(),
        ),
        total=1.0,
    ).sealed()
    assert contributions.total == 1.0
    with pytest.raises(ValidationError, match="mechanism paths"):
        ResearchContributionReport(
            report_id="contributions-duplicate",
            contributions=(
                ResearchContribution(mechanism_path="mechanism-a", amount=0.4).sealed(),
                ResearchContribution(mechanism_path="mechanism-a", amount=0.6).sealed(),
            ),
            total=1.0,
        )


def test_research_portfolio_reconciles_compute_data_review_and_redundancy_costs() -> None:
    programme = _programme()
    candidate = ResearchPortfolioCandidate(
        candidate_id="portfolio-candidate-1",
        programme=programme,
        expected_validity=0.8,
        decision_value=20.0,
        novelty=0.5,
        strategic_fit=0.5,
        compute_cost=1.0,
        data_cost=0.5,
        review_cost=0.25,
        redundancy_penalty=0.25,
        total_cost=2.0,
        expected_voi=2.0,
        priority_score=2.0,
        deadline=AS_OF + timedelta(days=1),
    ).sealed()
    budget = ResearchBudget(
        compute_limit=2.0,
        data_limit=1.0,
        review_limit=1.0,
        total_limit=4.0,
    ).sealed()

    first = rank_research_portfolio(
        portfolio_id="portfolio-1",
        as_of=AS_OF,
        budget=budget,
        candidates=(candidate,),
    )
    second = rank_research_portfolio(
        portfolio_id="portfolio-1",
        as_of=AS_OF,
        budget=budget,
        candidates=(candidate,),
    )
    assert isinstance(first, ResearchPortfolio)
    assert first.selected_candidate_ids == (candidate.candidate_id,)
    assert first.total_selected_cost == 2.0
    assert first.model_dump_json() == second.model_dump_json()

    second_candidate = candidate.model_copy(
        update={
            "candidate_id": "portfolio-candidate-2",
            "programme": _programme(programme_id="programme-2"),
            "content_hash": None,
        }
    ).sealed()
    wider_budget = ResearchBudget(
        compute_limit=4.0,
        data_limit=2.0,
        review_limit=2.0,
        total_limit=8.0,
    ).sealed()
    tie = rank_research_portfolio(
        portfolio_id="portfolio-tie",
        as_of=AS_OF,
        budget=wider_budget,
        candidates=(second_candidate, candidate),
    )
    assert tie.selected_candidate_ids == (candidate.candidate_id, second_candidate.candidate_id)

    with pytest.raises(ValidationError, match="priority score"):
        candidate.model_copy(update={"priority_score": 3.0, "content_hash": None})
    with pytest.raises(ValidationError, match="expected VOI"):
        candidate.model_copy(update={"expected_voi": 2.0 + 5e-13, "content_hash": None})
    with pytest.raises(ValidationError, match="selected costs"):
        first.model_copy(update={"selected_compute_cost": 1.0 + 5e-13, "content_hash": None})
    with pytest.raises(ValidationError, match="portfolio cutoff"):
        rank_research_portfolio(
            portfolio_id="portfolio-future-programme",
            as_of=AS_OF - timedelta(seconds=1),
            budget=budget,
            candidates=(candidate,),
        )


def test_research_portfolio_emits_explicit_stop_reasons() -> None:
    programme = _programme()
    candidate = ResearchPortfolioCandidate(
        candidate_id="portfolio-candidate-1",
        programme=programme,
        expected_validity=1.0,
        decision_value=4.0,
        novelty=1.0,
        strategic_fit=1.0,
        compute_cost=1.0,
        data_cost=1.0,
        review_cost=1.0,
        redundancy_penalty=1.0,
        total_cost=4.0,
        expected_voi=0.0,
        priority_score=1.0,
        deadline=AS_OF + timedelta(days=1),
    ).sealed()
    budget = ResearchBudget(
        compute_limit=2.0,
        data_limit=2.0,
        review_limit=2.0,
        total_limit=6.0,
    ).sealed()
    positive = candidate.model_copy(
        update={
            "decision_value": 8.0,
            "expected_voi": 4.0,
            "priority_score": 2.0,
            "content_hash": None,
        }
    ).sealed()
    stopped_programme = programme.model_copy(
        update={"status": "stopped", "content_hash": None}
    ).sealed()
    with pytest.raises(ValidationError, match="stopped programme"):
        positive.model_copy(update={"programme": stopped_programme, "content_hash": None})
    cases = (
        (candidate, budget, AS_OF, "non_positive_voi"),
        (
            positive.model_copy(update={"redundant": True, "content_hash": None}).sealed(),
            budget,
            AS_OF,
            "redundancy",
        ),
        (positive, budget, positive.deadline, "deadline"),
        (
            positive.model_copy(update={"robust": False, "content_hash": None}).sealed(),
            budget,
            AS_OF,
            "robustness",
        ),
        (
            positive.model_copy(
                update={"uncertainty_decision_changing": False, "content_hash": None}
            ).sealed(),
            budget,
            AS_OF,
            "non_decision_changing_uncertainty",
        ),
        (
            positive,
            ResearchBudget(
                compute_limit=0.5,
                data_limit=2.0,
                review_limit=2.0,
                total_limit=4.5,
            ).sealed(),
            AS_OF,
            "budget",
        ),
    )
    for item, item_budget, as_of, reason in cases:
        portfolio = rank_research_portfolio(
            portfolio_id=f"portfolio-{reason}",
            as_of=as_of,
            budget=item_budget,
            candidates=(item,),
        )
        assert portfolio.selected_candidate_ids == ()
        assert portfolio.stop_reason == reason


def test_research_tree_rejects_duplicate_active_hypothesis_and_excess_depth() -> None:
    programme = _programme(max_tree_depth=1)
    team = ResearchTeam(
        team_id="team-1",
        programme_id=programme.programme_id,
        role="hypothesis_architect",
        member_ids=("researcher-1",),
        compute_limit=10.0,
    ).sealed()
    root = ResearchTreeNode(
        node_id="node-1",
        programme_id=programme.programme_id,
        team_id=team.team_id,
        hypothesis_id="hypothesis-a",
        depth=0,
        compute_cost=1.0,
    ).sealed()
    duplicate = ResearchTreeNode(
        node_id="node-2",
        programme_id=programme.programme_id,
        team_id=team.team_id,
        hypothesis_id="hypothesis-a",
        depth=0,
        compute_cost=1.0,
    ).sealed()

    with pytest.raises(ValidationError, match="duplicate active hypothesis"):
        ResearchTree(
            tree_id="tree-1",
            programme=programme,
            teams=(team,),
            nodes=(root, duplicate),
        )

    too_deep = ResearchTreeNode(
        node_id="node-3",
        programme_id=programme.programme_id,
        team_id=team.team_id,
        hypothesis_id="hypothesis-b",
        parent_node_id=root.node_id,
        depth=2,
        compute_cost=1.0,
    ).sealed()
    with pytest.raises(ValidationError, match="tree depth"):
        ResearchTree(
            tree_id="tree-1",
            programme=programme,
            teams=(team,),
            nodes=(root, too_deep),
        )

    replication_team = ResearchTeam(
        team_id="replication-team-1",
        programme_id=programme.programme_id,
        role="replication_team",
        member_ids=("replicator-1",),
        compute_limit=10.0,
    ).sealed()
    first_replication = ResearchTreeNode(
        node_id="replication-1",
        programme_id=programme.programme_id,
        team_id=replication_team.team_id,
        hypothesis_id=root.hypothesis_id,
        parent_node_id=root.node_id,
        depth=1,
        compute_cost=1.0,
        node_kind="replication",
        replicates_node_id=root.node_id,
    ).sealed()
    valid_replication_tree = ResearchTree(
        tree_id="tree-valid-replication",
        programme=programme,
        teams=(team, replication_team),
        nodes=(root, first_replication),
    ).sealed()
    assert valid_replication_tree.authority == "candidate_only"

    wrong_role_replication = first_replication.model_copy(
        update={"team_id": team.team_id, "content_hash": None}
    ).sealed()
    with pytest.raises(ValidationError, match="replication team"):
        ResearchTree(
            tree_id="tree-wrong-replication-role",
            programme=programme,
            teams=(team,),
            nodes=(root, wrong_role_replication),
        )
    chained_replication = ResearchTreeNode(
        node_id="replication-2",
        programme_id=programme.programme_id,
        team_id=replication_team.team_id,
        hypothesis_id=root.hypothesis_id,
        parent_node_id=root.node_id,
        depth=1,
        compute_cost=1.0,
        node_kind="replication",
        replicates_node_id=first_replication.node_id,
    ).sealed()
    with pytest.raises(ValidationError, match="original hypothesis node"):
        ResearchTree(
            tree_id="tree-replication-chain",
            programme=programme,
            teams=(team, replication_team),
            nodes=(root, first_replication, chained_replication),
        )


def test_research_tree_rejects_invalid_parent_and_compute_breaches() -> None:
    programme = _programme()
    team = ResearchTeam(
        team_id="team-1",
        programme_id=programme.programme_id,
        role="hypothesis_architect",
        member_ids=("researcher-1",),
        compute_limit=10.0,
    ).sealed()
    orphan = ResearchTreeNode(
        node_id="node-orphan",
        programme_id=programme.programme_id,
        team_id=team.team_id,
        hypothesis_id="hypothesis-a",
        parent_node_id="missing-parent",
        depth=1,
        compute_cost=1.0,
    ).sealed()
    with pytest.raises(ValidationError, match="follow its parent"):
        ResearchTree(
            tree_id="tree-orphan",
            programme=programme,
            teams=(team,),
            nodes=(orphan,),
        )

    root = orphan.model_copy(
        update={
            "node_id": "node-root",
            "parent_node_id": None,
            "depth": 0,
            "content_hash": None,
        }
    ).sealed()
    low_limit_team = team.model_copy(update={"compute_limit": 0.5, "content_hash": None}).sealed()
    with pytest.raises(ValidationError, match="team compute limit"):
        ResearchTree(
            tree_id="tree-team-cost",
            programme=programme,
            teams=(low_limit_team,),
            nodes=(root,),
        )

    second_root = root.model_copy(
        update={
            "node_id": "node-root-2",
            "hypothesis_id": "hypothesis-b",
            "content_hash": None,
        }
    ).sealed()
    first_critique = ResearchCritiqueReceipt(
        critique_id="critique-duplicate",
        node_id=root.node_id,
        reviewer_id="reviewer-1",
        recorded_at=AS_OF + timedelta(minutes=2),
        findings=("Review first root.",),
        evidence_binding=programme.evidence_binding,
    ).sealed()
    second_critique = first_critique.model_copy(
        update={"node_id": second_root.node_id, "content_hash": None}
    ).sealed()
    reviewed_root = root.model_copy(
        update={"critique": first_critique, "content_hash": None}
    ).sealed()
    reviewed_second_root = second_root.model_copy(
        update={"critique": second_critique, "content_hash": None}
    ).sealed()
    with pytest.raises(ValidationError, match="critique IDs"):
        ResearchTree(
            tree_id="tree-duplicate-critique",
            programme=programme,
            teams=(team,),
            nodes=(reviewed_root, reviewed_second_root),
        )

    low_budget = ResearchBudget(
        compute_limit=1.0,
        data_limit=5.0,
        review_limit=3.0,
        total_limit=9.0,
    ).sealed()
    low_budget_programme = programme.model_copy(
        update={"budget": low_budget, "content_hash": None}
    ).sealed()
    with pytest.raises(ValidationError, match="programme compute limit"):
        ResearchTree(
            tree_id="tree-programme-cost",
            programme=low_budget_programme,
            teams=(team,),
            nodes=(root, second_root),
        )


def test_research_tree_requires_recorded_critique_before_plan() -> None:
    programme = _programme()
    hypothesis = programme.hypothesis_families[0].hypotheses[0]
    team = ResearchTeam(
        team_id="team-1",
        programme_id=programme.programme_id,
        role="experiment_designer",
        member_ids=("designer-1",),
        compute_limit=10.0,
    ).sealed()
    node_values = {
        "node_id": "node-1",
        "programme_id": programme.programme_id,
        "team_id": team.team_id,
        "hypothesis_id": hypothesis.hypothesis_id,
        "depth": 0,
        "compute_cost": 1.0,
    }
    node = ResearchTreeNode(**node_values).sealed()
    tree = ResearchTree(
        tree_id="tree-1",
        programme=programme,
        teams=(team,),
        nodes=(node,),
    ).sealed()
    plan = ExperimentPlan(
        experiment_id="experiment-1",
        tree_node_id=node.node_id,
        hypothesis=hypothesis,
        preregistered_at=AS_OF + timedelta(minutes=2),
        evidence_binding=programme.evidence_binding,
        dataset_snapshot_hash=programme.evidence_binding.snapshot.content_hash,
        split_policy_id="split-policy-1",
        metric_ids=("metric-1",),
        baseline_ids=("baseline-1",),
        ablation_ids=("ablation-1",),
        cost_model_id="cost-model-1",
        stop_rules=("stop-rule-1",),
        locked_fields=LOCKED_FIELDS,
        author_id="designer-1",
    ).sealed()

    with pytest.raises(ValueError, match="recorded critique"):
        tree.validate_plan(plan)

    critique = ResearchCritiqueReceipt(
        critique_id="critique-1",
        node_id=node.node_id,
        reviewer_id="reviewer-1",
        recorded_at=AS_OF + timedelta(seconds=90),
        findings=("Baseline choice requires adversarial review.",),
        evidence_binding=programme.evidence_binding,
    ).sealed()
    reviewed_node = ResearchTreeNode(**(node_values | {"critique": critique})).sealed()
    reviewed_tree = ResearchTree(
        tree_id="tree-1",
        programme=programme,
        teams=(team,),
        nodes=(reviewed_node,),
    ).sealed()
    reviewed_tree.validate_plan(plan)

    equal_time_plan = plan.model_copy(
        update={
            "preregistered_at": critique.recorded_at,
            "content_hash": None,
        }
    ).sealed()
    with pytest.raises(ValueError, match="before preregistration"):
        reviewed_tree.validate_plan(equal_time_plan)

    self_review = critique.model_copy(
        update={"reviewer_id": "designer-1", "content_hash": None}
    ).sealed()
    self_reviewed_node = ResearchTreeNode(**(node_values | {"critique": self_review})).sealed()
    self_reviewed_tree = ResearchTree(
        tree_id="tree-self-review",
        programme=programme,
        teams=(team,),
        nodes=(self_reviewed_node,),
    ).sealed()
    with pytest.raises(ValueError, match="review their own"):
        self_reviewed_tree.validate_plan(plan)

    substituted_hypothesis = hypothesis.model_copy(
        update={"statement": "Altered same-ID hypothesis.", "content_hash": None}
    ).sealed()
    substituted_plan = plan.model_copy(
        update={"hypothesis": substituted_hypothesis, "content_hash": None}
    ).sealed()
    with pytest.raises(ValueError, match="programme hypothesis"):
        reviewed_tree.validate_plan(substituted_plan)

    stopped_node = reviewed_node.model_copy(
        update={"status": "stopped", "content_hash": None}
    ).sealed()
    stopped_node_tree = ResearchTree(
        tree_id="tree-stopped-node",
        programme=programme,
        teams=(team,),
        nodes=(stopped_node,),
    ).sealed()
    with pytest.raises(ValueError, match="stopped"):
        stopped_node_tree.validate_plan(plan)

    stopped_programme = programme.model_copy(
        update={"status": "stopped", "content_hash": None}
    ).sealed()
    stopped_programme_tree = ResearchTree(
        tree_id="tree-stopped-programme",
        programme=stopped_programme,
        teams=(team,),
        nodes=(reviewed_node,),
    ).sealed()
    with pytest.raises(ValueError, match="stopped"):
        stopped_programme_tree.validate_plan(plan)


def test_v6_role_grants_deny_omissions_and_capital_critical_tools() -> None:
    capability = "science.programme.plan"
    assert authorize_v6_research_tool("director", capability) == capability

    with pytest.raises(CapabilityDenied, match="not granted"):
        authorize_v6_research_tool("director", "science.fixture.evaluate")
    with pytest.raises(CapabilityDenied, match="not granted"):
        authorize_v6_research_tool("unknown", capability)  # type: ignore[arg-type]
    for forbidden in (
        "broker.submit_order",
        "execution.submit",
        "fund.allocate",
        "promotion.approve",
        "risk.decide",
        "source.direct_http.fetch",
    ):
        with pytest.raises(CapabilityDenied, match="capital-critical"):
            authorize_v6_research_tool("director", forbidden)


def test_research_programme_requires_two_competing_hypotheses() -> None:
    binding = _evidence_binding()
    first = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", binding)
    second = _hypothesis("hypothesis-b", "mechanism-b", "hypothesis-a", binding)
    family = HypothesisFamily(
        family_id="family-1",
        programme_id="programme-1",
        hypotheses=(first, second),
    ).sealed()
    budget = ResearchBudget(
        compute_limit=10.0,
        data_limit=5.0,
        review_limit=3.0,
        total_limit=18.0,
    ).sealed()

    programme = ResearchProgramme(
        programme_id="programme-1",
        mandate="Test competing candidate mechanisms.",
        as_of=AS_OF,
        owner_id="research-director-1",
        expected_decision_value=1.0,
        budget=budget,
        max_team_count=3,
        max_tree_depth=2,
        hypothesis_families=(family,),
        evidence_binding=binding,
    ).sealed()
    assert programme.authority == "candidate_only"
    assert programme.release_disposition == "engineering_only"

    one_hypothesis_family = HypothesisFamily.model_construct(
        family_id="family-1",
        programme_id="programme-1",
        hypotheses=(first,),
        content_hash=None,
    )
    with pytest.raises(ValidationError, match="at least two competing hypotheses"):
        ResearchProgramme(
            programme_id="programme-1",
            mandate="Invalid single-hypothesis programme.",
            as_of=AS_OF,
            owner_id="research-director-1",
            expected_decision_value=1.0,
            budget=budget,
            max_team_count=3,
            max_tree_depth=2,
            hypothesis_families=(one_hypothesis_family,),
            evidence_binding=binding,
        )


def test_research_programme_rejects_hypothesis_evidence_outside_programme_binding() -> None:
    programme_binding = _evidence_binding()
    future_binding = _evidence_binding(as_of=AS_OF + timedelta(days=1))
    first = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", future_binding)
    second = _hypothesis("hypothesis-b", "mechanism-b", "hypothesis-a", future_binding)
    family = HypothesisFamily(
        family_id="family-1",
        programme_id="programme-1",
        hypotheses=(first, second),
    ).sealed()
    budget = ResearchBudget(
        compute_limit=1.0,
        data_limit=1.0,
        review_limit=1.0,
        total_limit=3.0,
    ).sealed()

    with pytest.raises(ValidationError, match="programme evidence binding"):
        ResearchProgramme(
            programme_id="programme-1",
            mandate="Reject substituted hypothesis evidence.",
            as_of=AS_OF,
            owner_id="research-director-1",
            expected_decision_value=1.0,
            budget=budget,
            max_team_count=2,
            max_tree_depth=1,
            hypothesis_families=(family,),
            evidence_binding=programme_binding,
        )


def test_research_evidence_binding_rejects_future_or_unretained_provenance() -> None:
    valid = _evidence_binding()
    assert valid.content_hash is not None

    with pytest.raises(ValidationError, match="available after research cutoff"):
        _evidence_binding(source_available_at=AS_OF + timedelta(seconds=1))

    with pytest.raises(ValidationError, match="retained receipt"):
        _evidence_binding(retained_hash="f" * 64)


def test_experiment_plan_requires_locked_preregistration_surface() -> None:
    binding = _evidence_binding()
    hypothesis = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", binding)
    values = {
        "experiment_id": "experiment-1",
        "tree_node_id": "node-1",
        "hypothesis": hypothesis,
        "preregistered_at": AS_OF + timedelta(minutes=2),
        "evidence_binding": binding,
        "dataset_snapshot_hash": binding.snapshot.content_hash,
        "split_policy_id": "split-policy-1",
        "metric_ids": ("metric-1",),
        "baseline_ids": ("baseline-1",),
        "ablation_ids": ("ablation-1",),
        "cost_model_id": "cost-model-1",
        "stop_rules": ("stop-rule-1",),
        "locked_fields": LOCKED_FIELDS,
        "author_id": "experiment-designer-1",
    }

    plan = ExperimentPlan(**values).sealed()
    assert plan.content_hash is not None
    assert plan.authority == "candidate_only"

    with pytest.raises(ValidationError, match="locked fields"):
        ExperimentPlan(**(values | {"locked_fields": LOCKED_FIELDS[:-1]}))
    with pytest.raises(ValidationError, match="snapshot hash"):
        ExperimentPlan(**(values | {"dataset_snapshot_hash": "f" * 64}))
    with pytest.raises(ValidationError, match="before its evidence cutoff"):
        ExperimentPlan(**(values | {"preregistered_at": AS_OF - timedelta(seconds=1)}))


def test_novelty_report_is_bound_to_hypothesis_and_pit_evidence() -> None:
    binding = _evidence_binding()
    hypothesis = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", binding)
    values = {
        "novelty_report_id": "novelty-1",
        "hypothesis": hypothesis,
        "assessed_at": AS_OF + timedelta(minutes=1),
        "evidence_binding": binding,
        "prior_experiment_ids": ("experiment-prior-1",),
        "surfaced_negative_result_ids": (),
        "limitations": ("Internal records only; no external novelty claim.",),
        "auditor_id": "novelty-auditor-1",
    }

    report = NoveltyReport(**values).sealed()
    assert report.calibration_status == "not_calibrated"
    assert report.novelty_status == "not_established"

    with pytest.raises(ValidationError, match="before its evidence cutoff"):
        NoveltyReport(**(values | {"assessed_at": AS_OF - timedelta(seconds=1)}))
    with pytest.raises(ValidationError, match="evidence must match"):
        other_binding = _evidence_binding(source_available_at=AS_OF - timedelta(days=2))
        NoveltyReport(**(values | {"evidence_binding": other_binding}))


def test_research_lifecycle_records_cannot_predate_retained_receipt() -> None:
    binding = _evidence_binding()
    hypothesis = _hypothesis("hypothesis-a", "mechanism-a", "hypothesis-b", binding)
    before_receipt = binding.original_receipt.recorded_at - timedelta(seconds=1)

    with pytest.raises(ValidationError, match="retained receipt"):
        NoveltyReport(
            novelty_report_id="novelty-1",
            hypothesis=hypothesis,
            assessed_at=before_receipt,
            evidence_binding=binding,
            limitations=("Internal evidence only.",),
            auditor_id="novelty-auditor-1",
        )
    with pytest.raises(ValidationError, match="retained receipt"):
        ExperimentPlan(
            experiment_id="experiment-1",
            tree_node_id="node-1",
            hypothesis=hypothesis,
            preregistered_at=before_receipt,
            evidence_binding=binding,
            dataset_snapshot_hash=binding.snapshot.content_hash,
            split_policy_id="split-policy-1",
            metric_ids=("metric-1",),
            baseline_ids=("baseline-1",),
            ablation_ids=("ablation-1",),
            cost_model_id="cost-model-1",
            stop_rules=("stop-rule-1",),
            locked_fields=LOCKED_FIELDS,
            author_id="experiment-designer-1",
        )


def test_v6_science_contracts_are_public_and_model_copy_fail_closed() -> None:
    from aegis import research_lab

    for name in (
        "ExperimentPlan",
        "ExperimentRun",
        "ExperimentRunAbstention",
        "Hypothesis",
        "HypothesisFamily",
        "NegativeResult",
        "NoveltyReport",
        "ReplicationRun",
        "ResearchArchive",
        "ResearchArtifactReceiptReference",
        "ResearchBudget",
        "ResearchClaim",
        "ResearchContribution",
        "ResearchContributionReport",
        "ResearchCritiqueReceipt",
        "ResearchEvidenceBinding",
        "ResearchProgramme",
        "ResearchPostmortem",
        "ResearchPortfolio",
        "ResearchPortfolioCandidate",
        "ScienceReport",
        "ResearchTeam",
        "ResearchTree",
        "ResearchTreeNode",
        "VerificationPackage",
        "V6_ROLE_TOOL_GRANTS",
        "authorize_v6_research_tool",
        "evaluate_registered_fixture",
        "load_experiment_run",
        "record_experiment_run",
        "rank_research_portfolio",
        "science_report_view",
    ):
        assert getattr(research_lab, name)

    binding = _evidence_binding()
    with pytest.raises(ValueError, match="unknown fields"):
        binding.model_copy(update={"unexpected": "value"})
    with pytest.raises(ValidationError, match="content hash mismatch"):
        binding.model_copy(update={"binding_id": "replacement-binding"})
