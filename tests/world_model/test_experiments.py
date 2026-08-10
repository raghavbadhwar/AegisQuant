from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aegis.world_model.experiments import (
    ExperimentStatus,
    ModelRiskTier,
    TemporalEvaluationPlan,
    TemporalSplit,
    TemporalSplitKind,
    WorldModelExperimentLedger,
    WorldModelExperimentManifest,
)

NOW = datetime(2026, 8, 8, tzinfo=UTC)


def temporal_evaluation_plan() -> TemporalEvaluationPlan:
    return TemporalEvaluationPlan(
        development=TemporalSplit(
            kind=TemporalSplitKind.DEVELOPMENT,
            starts_at=NOW - timedelta(days=40),
            ends_at=NOW - timedelta(days=31),
        ),
        calibration=TemporalSplit(
            kind=TemporalSplitKind.CALIBRATION,
            starts_at=NOW - timedelta(days=30),
            ends_at=NOW - timedelta(days=21),
        ),
        scenario_validation=TemporalSplit(
            kind=TemporalSplitKind.SCENARIO_VALIDATION,
            starts_at=NOW - timedelta(days=20),
            ends_at=NOW - timedelta(days=11),
        ),
        final_holdout=TemporalSplit(
            kind=TemporalSplitKind.FINAL_HOLDOUT,
            starts_at=NOW - timedelta(days=10),
            ends_at=NOW - timedelta(days=1),
        ),
    )


def manifest(**updates: object) -> WorldModelExperimentManifest:
    values: dict[str, object] = {
        "experiment_id": "world-model-experiment-1",
        "declared_hypothesis": "A lagged capex mechanism improves scenario coverage.",
        "declared_before_run": True,
        "declared_at": NOW,
        "causal_graph_version": "graph-v1",
        "mechanism_versions": (("capex-to-demand", "v1"),),
        "twin_versions": (("supplier-twin", "v1"),),
        "domain_pack_version": "ai-infrastructure-v1",
        "data_snapshot_id": "snapshot-v1",
        "belief_state_id": "belief-v1",
        "scenario_ids": ("scenario-v1",),
        "parameter_changes": (),
        "code_commit": "abc123",
        "container_digest": "sha256:container-v1",
        "random_seeds": (7,),
        "temporal_evaluation": temporal_evaluation_plan(),
        "author_id": "researcher-1",
        "status": ExperimentStatus.DECLARED,
        "model_risk_tier": ModelRiskTier.TIER_2,
    }
    values.update(updates)
    return WorldModelExperimentManifest(**values)


def test_world_model_experiment_manifest_rejects_tier_three() -> None:
    with pytest.raises(ValueError, match="capped at Tier 2"):
        manifest(model_risk_tier=ModelRiskTier.TIER_3)


def test_world_model_experiment_must_be_declared_before_run() -> None:
    with pytest.raises(ValueError, match="declared before run"):
        manifest(declared_before_run=False)


def test_experiment_temporal_evaluation_requires_non_overlapping_splits() -> None:
    plan = temporal_evaluation_plan()

    with pytest.raises(ValueError, match="chronological"):
        plan.model_copy(
            update={
                "calibration": plan.calibration.model_copy(
                    update={"ends_at": NOW - timedelta(days=10)}
                )
            }
        )


def test_experiment_cannot_start_before_its_declaration() -> None:
    with pytest.raises(ValueError, match="start before declaration"):
        manifest(
            status=ExperimentStatus.RUNNING,
            run_started_at=NOW - timedelta(seconds=1),
        )


def test_experiment_manifest_seals_deterministically() -> None:
    sealed = manifest().sealed()

    assert sealed.content_hash
    assert sealed.sealed().content_hash == sealed.content_hash
    assert WorldModelExperimentManifest(**sealed.model_dump()).content_hash == sealed.content_hash


def test_experiment_manifest_rejects_mismatched_content_hash() -> None:
    payload = manifest().sealed().model_dump()
    payload["content_hash"] = "e" * 64

    with pytest.raises(ValueError, match="content hash mismatch"):
        WorldModelExperimentManifest(**payload)


def test_experiment_manifest_requires_a_consistent_append_link() -> None:
    with pytest.raises(ValueError, match="first manifest"):
        manifest(previous_manifest_hash="a" * 64)

    with pytest.raises(ValueError, match="append link"):
        manifest(manifest_sequence=2)


def test_declared_experiment_cannot_contain_run_timestamps() -> None:
    with pytest.raises(ValueError, match="declared status"):
        manifest(run_started_at=NOW)


def test_terminal_experiment_status_requires_complete_lifecycle_timestamps() -> None:
    with pytest.raises(ValueError, match="terminal status"):
        manifest(status=ExperimentStatus.COMPLETED)


def test_experiment_ledger_rejects_a_forged_predecessor_link() -> None:
    initial = manifest().sealed()
    forged = manifest(
        experiment_id="world-model-experiment-2",
        parent_experiment_id="nonexistent-experiment",
        manifest_sequence=2,
        previous_manifest_hash="a" * 64,
    ).sealed()

    with pytest.raises(ValueError, match="predecessor"):
        WorldModelExperimentLedger(manifests=(initial, forged))


def test_experiment_ledger_rejects_a_second_root_manifest() -> None:
    initial = manifest().sealed()
    second_root = manifest(experiment_id="world-model-experiment-2").sealed()

    with pytest.raises(ValueError, match="single root"):
        WorldModelExperimentLedger(manifests=(initial, second_root))


def test_experiment_ledger_appends_an_exact_sealed_successor() -> None:
    initial = manifest().sealed()
    ledger = WorldModelExperimentLedger(manifests=(initial,)).sealed()
    successor = manifest(
        experiment_id="world-model-experiment-2",
        parent_experiment_id=initial.experiment_id,
        manifest_sequence=2,
        previous_manifest_hash=initial.content_hash,
    ).sealed()

    extended = ledger.append(successor)

    assert extended.manifests == (initial, successor)
    assert extended.content_hash is not None
