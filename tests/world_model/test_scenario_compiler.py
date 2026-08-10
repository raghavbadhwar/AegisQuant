from datetime import UTC, datetime

import pytest

from aegis.world_model import ScenarioIntervention, WorldSnapshot, WorldVariable, scenario
from aegis.world_model.contracts import VariableProvenance

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def snapshot() -> WorldSnapshot:
    return WorldSnapshot(
        snapshot_id="world-compiler-1",
        as_of=NOW,
        pit_snapshot_hash="a" * 64,
        causal_graph_hash="b" * 64,
        variables=(
            WorldVariable(
                variable_id="hyperscaler.ai_capex_growth",
                value=0.2,
                unit="ratio",
                provenance=VariableProvenance.OBSERVED,
                available_at=NOW,
                evidence_ids=("e-1",),
                uncertainty_label="empirical",
            ),
        ),
        random_seed=42,
        code_revision="test-revision",
    )


def intervention() -> ScenarioIntervention:
    return ScenarioIntervention(
        intervention_id="capex-slowdown",
        target_variable_id="hyperscaler.ai_capex_growth",
        relative_change=-0.2,
        starts_at=NOW,
        rationale="candidate stress",
        assumption_ids=("a-1",),
    )


def test_compiler_rejects_unsealed_world_snapshot() -> None:
    with pytest.raises(ValueError, match="sealed"):
        scenario.compile_scenario(snapshot(), (intervention(),))


def test_compiler_rejects_intervention_for_unknown_world_variable() -> None:
    unknown_target = intervention().model_copy(
        update={"target_variable_id": "hbm.supply_normalisation_date"}
    )

    with pytest.raises(ValueError, match="absent"):
        scenario.compile_scenario(snapshot().sealed(), (unknown_target,))


def test_compiler_rejects_intervention_that_starts_before_snapshot_as_of() -> None:
    past_intervention = intervention().model_copy(
        update={"starts_at": datetime(2023, 12, 31, tzinfo=UTC)}
    )

    with pytest.raises(ValueError, match="before world snapshot"):
        scenario.compile_scenario(snapshot().sealed(), (past_intervention,))


def test_public_intervention_application_rejects_a_pre_snapshot_shock() -> None:
    past_intervention = intervention().model_copy(
        update={"starts_at": datetime(2023, 12, 31, tzinfo=UTC)}
    )

    with pytest.raises(ValueError, match="before world snapshot"):
        scenario.apply_intervention(snapshot().sealed(), past_intervention)


def test_public_intervention_application_rejects_a_tampered_sealed_snapshot() -> None:
    sealed_snapshot = snapshot().sealed()

    with pytest.raises(ValueError, match="content hash mismatch"):
        sealed_snapshot.model_copy(
            update={"variables": (sealed_snapshot.variables[0].model_copy(update={"value": 0.9}),)}
        )


def test_public_intervention_application_revalidates_tampered_interventions() -> None:
    with pytest.raises(ValueError, match="exactly one change type"):
        intervention().model_copy(update={"absolute_change": 0.1})


def test_compiler_rejects_conflicting_interventions_at_the_same_time() -> None:
    conflicting_intervention = intervention().model_copy(
        update={"intervention_id": "capex-growth", "relative_change": 0.1}
    )

    with pytest.raises(ValueError, match="conflicting"):
        scenario.compile_scenario(snapshot().sealed(), (intervention(), conflicting_intervention))


def test_compiler_rejects_duplicate_intervention_identifiers() -> None:
    duplicate_identifier = intervention().model_copy(
        update={"relative_change": 0.1, "starts_at": datetime(2024, 2, 1, tzinfo=UTC)}
    )

    with pytest.raises(ValueError, match="intervention IDs must be unique"):
        scenario.compile_scenario(snapshot().sealed(), (intervention(), duplicate_identifier))


def test_compiler_returns_a_sealed_candidate_only_plan_in_time_order() -> None:
    later_intervention = intervention().model_copy(
        update={
            "intervention_id": "capex-follow-up",
            "relative_change": 0.1,
            "starts_at": datetime(2024, 2, 1, tzinfo=UTC),
        }
    )
    sealed_snapshot = snapshot().sealed()

    compiled = scenario.compile_scenario(sealed_snapshot, (later_intervention, intervention()))

    assert compiled.world_snapshot_hash == sealed_snapshot.content_hash
    assert compiled.interventions == (intervention(), later_intervention)
    assert compiled.authority == "candidate_only"
    assert compiled.content_hash


def test_compiled_scenario_rejects_a_mismatched_content_hash() -> None:
    compiled = scenario.compile_scenario(snapshot().sealed(), (intervention(),))
    payload = compiled.model_dump()
    payload["content_hash"] = "c" * 64

    with pytest.raises(ValueError, match="content hash mismatch"):
        scenario.CompiledScenario(**payload)


def test_direct_compiled_scenario_rejects_pre_snapshot_interventions() -> None:
    past_intervention = intervention().model_copy(
        update={"starts_at": datetime(2023, 12, 31, tzinfo=UTC)}
    )

    with pytest.raises(ValueError, match="before world snapshot"):
        scenario.CompiledScenario(
            world_snapshot_hash="a" * 64,
            snapshot_as_of=NOW,
            interventions=(past_intervention,),
            affected_variable_ids=("hyperscaler.ai_capex_growth",),
        ).sealed()


def test_compiled_scenario_sealing_revalidates_model_copy_tampering() -> None:
    compiled = scenario.compile_scenario(snapshot().sealed(), (intervention(),))

    with pytest.raises(ValueError, match="before world snapshot"):
        compiled.model_copy(update={"snapshot_as_of": datetime(2024, 2, 1, tzinfo=UTC)})
