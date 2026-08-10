"""Deterministic, candidate-only world-state scenario propagation."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel

from .contracts import ScenarioIntervention, VariableProvenance, WorldSnapshot, WorldVariable


class ScenarioResult(CandidateContractModel):
    """Research output only; deliberately contains no portfolio or order fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intervention_id: str
    variables: tuple[WorldVariable, ...]


class CompiledScenario(CandidateContractModel):
    """Sealed, candidate-only plan for deterministic scenario evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_as_of: AwareDatetime
    interventions: tuple[ScenarioIntervention, ...]
    affected_variable_ids: tuple[str, ...]
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self) -> CompiledScenario:
        intervention_ids = [intervention.intervention_id for intervention in self.interventions]
        if any(not intervention_id for intervention_id in intervention_ids) or len(
            intervention_ids
        ) != len(set(intervention_ids)):
            raise ValueError("scenario intervention IDs must be unique and nonempty")
        if any(intervention.starts_at < self.snapshot_as_of for intervention in self.interventions):
            raise ValueError("scenario intervention cannot start before world snapshot as_of")
        targets_at_start = {
            (intervention.target_variable_id, intervention.starts_at)
            for intervention in self.interventions
        }
        if len(targets_at_start) != len(self.interventions):
            raise ValueError("scenario has conflicting interventions for one target and start time")
        expected_variable_ids = tuple(
            sorted({intervention.target_variable_id for intervention in self.interventions})
        )
        if self.affected_variable_ids != expected_variable_ids:
            raise ValueError("compiled scenario affected variable IDs must match interventions")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("compiled scenario content hash mismatch")
        return self

    def sealed(self) -> CompiledScenario:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = CompiledScenario.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def _validated_sealed_snapshot(
    snapshot: WorldSnapshot, *, context: str
) -> tuple[WorldSnapshot, str]:
    if snapshot.content_hash is None:
        raise ValueError(f"{context} requires a sealed world snapshot")
    validated = WorldSnapshot.model_validate(snapshot.model_dump(mode="json"))
    if validated.content_hash is None:
        raise ValueError(f"{context} requires a sealed world snapshot")
    return validated, validated.content_hash


def _validate_intervention_timing(
    snapshot: WorldSnapshot, intervention: ScenarioIntervention
) -> None:
    if intervention.starts_at < snapshot.as_of:
        raise ValueError("scenario intervention cannot start before world snapshot as_of")


def _validated_intervention(intervention: ScenarioIntervention) -> ScenarioIntervention:
    return ScenarioIntervention.model_validate(intervention.model_dump(mode="json"))


def apply_intervention(
    snapshot: WorldSnapshot, intervention: ScenarioIntervention
) -> ScenarioResult:
    """Apply one explicit shock deterministically without asserting factuality."""
    snapshot, snapshot_hash = _validated_sealed_snapshot(snapshot, context="scenario")
    intervention = _validated_intervention(intervention)
    _validate_intervention_timing(snapshot, intervention)
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
        world_snapshot_hash=snapshot_hash,
        intervention_id=intervention.intervention_id,
        variables=tuple(variables),
    )


def compile_scenario(
    snapshot: WorldSnapshot, interventions: tuple[ScenarioIntervention, ...]
) -> CompiledScenario:
    """Reject unsealed inputs before a caller can construct a simulation plan."""
    snapshot, snapshot_hash = _validated_sealed_snapshot(snapshot, context="scenario compiler")
    interventions = tuple(_validated_intervention(intervention) for intervention in interventions)
    variable_ids = {variable.variable_id for variable in snapshot.variables}
    if any(intervention.target_variable_id not in variable_ids for intervention in interventions):
        raise ValueError("scenario intervention target is absent from world snapshot")
    for intervention in interventions:
        _validate_intervention_timing(snapshot, intervention)
    intervention_ids = [intervention.intervention_id for intervention in interventions]
    if any(not intervention_id for intervention_id in intervention_ids) or len(
        intervention_ids
    ) != len(set(intervention_ids)):
        raise ValueError("scenario intervention IDs must be unique and nonempty")
    targets_at_start = {
        (intervention.target_variable_id, intervention.starts_at) for intervention in interventions
    }
    if len(targets_at_start) != len(interventions):
        raise ValueError("scenario has conflicting interventions for one target and start time")
    ordered_interventions = tuple(
        sorted(
            interventions,
            key=lambda intervention: (intervention.starts_at, intervention.intervention_id),
        )
    )
    return CompiledScenario(
        world_snapshot_hash=snapshot_hash,
        snapshot_as_of=snapshot.as_of,
        interventions=ordered_interventions,
        affected_variable_ids=tuple(
            sorted({intervention.target_variable_id for intervention in ordered_interventions})
        ),
    ).sealed()
