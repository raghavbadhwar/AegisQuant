"""Immutable v4 world-state and intervention contracts.

Simulation requests constructed here are research candidates only; they cannot
produce orders or alter the v3 deterministic execution path.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel


class VariableProvenance(StrEnum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    PRIOR = "prior"
    STRESS_ASSUMPTION = "stress_assumption"


class WorldVariable(CandidateContractModel):
    """One unit-bearing state variable pinned to evidence and PIT availability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variable_id: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    provenance: VariableProvenance
    available_at: AwareDatetime
    evidence_ids: tuple[str, ...] = ()
    uncertainty_label: str = Field(min_length=1)

    @model_validator(mode="after")
    def observed_values_require_evidence(self) -> WorldVariable:
        if self.provenance == VariableProvenance.OBSERVED and not self.evidence_ids:
            raise ValueError("observed world variable requires evidence")
        return self


class WorldSnapshot(CandidateContractModel):
    """Content-addressed, not authenticated, information state at a PIT cutoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    as_of: AwareDatetime
    pit_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    causal_graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    variables: tuple[WorldVariable, ...]
    random_seed: int = Field(ge=0)
    code_revision: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def causal_and_pit_safe(self) -> WorldSnapshot:
        ids = [item.variable_id for item in self.variables]
        if len(ids) != len(set(ids)):
            raise ValueError("world snapshot variable IDs must be unique")
        if any(item.available_at > self.as_of for item in self.variables):
            raise ValueError("world snapshot contains future variable")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("world snapshot content hash mismatch")
        return self

    def sealed(self) -> WorldSnapshot:
        return self.model_copy(
            update={
                "content_hash": canonical_sha256(
                    self.model_dump(mode="json", exclude={"content_hash"})
                )
            }
        )


class ScenarioIntervention(CandidateContractModel):
    """Explicit non-factual shock; it must never be rendered as observed evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intervention_id: str = Field(min_length=1)
    target_variable_id: str = Field(min_length=1)
    relative_change: float | None = None
    absolute_change: float | None = None
    starts_at: AwareDatetime
    rationale: str = Field(min_length=1)
    assumption_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def intervention_is_explicit(self) -> ScenarioIntervention:
        if (self.relative_change is None) == (self.absolute_change is None):
            raise ValueError("scenario needs exactly one change type")
        return self
