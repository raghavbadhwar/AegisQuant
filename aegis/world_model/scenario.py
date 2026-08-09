"""Deterministic, candidate-only world-state scenario propagation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .contracts import ScenarioIntervention, VariableProvenance, WorldSnapshot, WorldVariable


class ScenarioResult(BaseModel):
    """Research output only; deliberately contains no portfolio or order fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intervention_id: str
    variables: tuple[WorldVariable, ...]


def apply_intervention(
    snapshot: WorldSnapshot, intervention: ScenarioIntervention
) -> ScenarioResult:
    """Apply one explicit shock deterministically without asserting factuality."""
    if snapshot.content_hash is None:
        raise ValueError("scenario requires a sealed world snapshot")
    changed = False
    variables: list[WorldVariable] = []
    for variable in snapshot.variables:
        if variable.variable_id != intervention.target_variable_id:
            variables.append(variable)
            continue
        changed = True
        value = (
            variable.value * (1 + intervention.relative_change)
            if intervention.relative_change is not None
            else variable.value + intervention.absolute_change  # type: ignore[operator]
        )
        variables.append(
            variable.model_copy(
                update={
                    "value": value,
                    "provenance": VariableProvenance.STRESS_ASSUMPTION,
                    "evidence_ids": (),
                    "uncertainty_label": "scenario-assumption",
                }
            )
        )
    if not changed:
        raise ValueError("scenario intervention target is absent from world snapshot")
    return ScenarioResult(
        world_snapshot_hash=snapshot.content_hash,
        intervention_id=intervention.intervention_id,
        variables=tuple(variables),
    )
