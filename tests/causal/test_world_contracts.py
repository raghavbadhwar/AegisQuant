from datetime import UTC, datetime

import pytest

from aegis.world_model import ScenarioIntervention, WorldSnapshot, WorldVariable
from aegis.world_model.contracts import VariableProvenance

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def variable(**updates: object) -> WorldVariable:
    values: dict[str, object] = {
        "variable_id": "ai-capex",
        "value": 0.2,
        "unit": "percent",
        "provenance": VariableProvenance.OBSERVED,
        "available_at": NOW,
        "evidence_ids": ("e-1",),
        "uncertainty_label": "empirical",
    }
    values.update(updates)
    return WorldVariable(**values)


def test_world_snapshot_rejects_future_state() -> None:
    with pytest.raises(ValueError, match="future"):
        WorldSnapshot(
            snapshot_id="world-1",
            as_of=NOW,
            pit_snapshot_hash="a" * 64,
            causal_graph_hash="b" * 64,
            variables=(variable(available_at=datetime(2025, 1, 1, tzinfo=UTC)),),
            random_seed=1,
            code_revision="abc",
        )


def test_world_snapshot_is_hash_sealed_and_interventions_are_nonambiguous() -> None:
    world = WorldSnapshot(
        snapshot_id="world-1",
        as_of=NOW,
        pit_snapshot_hash="a" * 64,
        causal_graph_hash="b" * 64,
        variables=(variable(),),
        random_seed=1,
        code_revision="abc",
    ).sealed()
    assert world.content_hash
    with pytest.raises(ValueError, match="exactly"):
        ScenarioIntervention(
            intervention_id="shock-1",
            target_variable_id="ai-capex",
            starts_at=NOW,
            rationale="stress",
            assumption_ids=("assumption-1",),
            relative_change=-0.2,
            absolute_change=-1.0,
        )
