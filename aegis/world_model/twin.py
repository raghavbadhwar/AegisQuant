"""Candidate-only digital-twin state contracts with no execution authority."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Literal, Protocol, runtime_checkable

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel

from .contracts import VariableProvenance, WorldSnapshot, WorldVariable

_STABLE_ID = r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$"
_SHA256 = r"^[0-9a-f]{64}$"


@runtime_checkable
class DigitalTwin(Protocol):
    """Candidate-only executable boundary; it provides no execution or promotion path."""

    @property
    def twin_id(self) -> str: ...

    def initial_state(self, snapshot: WorldSnapshot) -> TwinState: ...

    def transition(
        self,
        state: TwinState,
        inputs: Mapping[str, float],
        parameter_draw_id: str,
        time_step: timedelta,
    ) -> TwinTransition: ...

    def observe(self, state: TwinState) -> Mapping[str, float]: ...

    def validate(self, state: TwinState) -> tuple[InvariantViolation, ...]: ...


class InvariantViolation(CandidateContractModel):
    """A deterministic validation finding for a candidate twin state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    violation_id: str = Field(pattern=_STABLE_ID)
    invariant_id: str = Field(pattern=_STABLE_ID)
    twin_id: str = Field(pattern=_STABLE_ID)
    state_id: str = Field(pattern=_STABLE_ID)
    severity: Literal["warning", "error", "critical"]
    message: str = Field(min_length=1)
    affected_variable_ids: tuple[str, ...] = Field(min_length=1)


class TwinState(CandidateContractModel):
    """Immutable, PIT-safe state for one candidate digital twin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state_id: str = Field(pattern=_STABLE_ID)
    twin_id: str = Field(pattern=_STABLE_ID)
    domain_pack_id: str = Field(pattern=_STABLE_ID)
    domain_pack_version: str = Field(min_length=1)
    world_snapshot_hash: str = Field(pattern=_SHA256)
    world_snapshot: WorldSnapshot
    as_of: AwareDatetime
    variables: tuple[WorldVariable, ...] = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def is_pit_safe_and_hash_valid(self) -> TwinState:
        source_snapshot = WorldSnapshot.model_validate(self.world_snapshot.model_dump(mode="json"))
        if source_snapshot.content_hash is None:
            raise ValueError("twin state requires a sealed source world snapshot")
        if self.world_snapshot_hash != source_snapshot.content_hash:
            raise ValueError("twin state source world snapshot hash mismatch")
        if self.as_of < source_snapshot.as_of:
            raise ValueError("twin state cannot predate its source world snapshot")
        variables = tuple(
            WorldVariable.model_validate(variable.model_dump(mode="json"))
            for variable in self.variables
        )
        variable_ids = [variable.variable_id for variable in variables]
        if len(variable_ids) != len(set(variable_ids)):
            raise ValueError("twin state variable IDs must be unique")
        if any(variable.available_at > self.as_of for variable in variables):
            raise ValueError("twin state contains future variable")
        if any(
            variable.provenance == VariableProvenance.OBSERVED
            and variable.available_at > source_snapshot.as_of
            for variable in variables
        ):
            raise ValueError("twin state contains observed data after its source world snapshot")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("twin state content hash mismatch")
        return self

    def sealed(self) -> TwinState:
        """Return the deterministic, content-addressed candidate state."""
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = TwinState.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class TwinTransition(CandidateContractModel):
    """Candidate transition with its resulting state bound to one domain version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transition_id: str = Field(pattern=_STABLE_ID)
    twin_id: str = Field(pattern=_STABLE_ID)
    domain_pack_id: str = Field(pattern=_STABLE_ID)
    domain_pack_version: str = Field(min_length=1)
    from_state_id: str = Field(pattern=_STABLE_ID)
    from_state: TwinState
    to_state: TwinState
    parameter_draw_id: str = Field(pattern=_STABLE_ID)
    time_step: timedelta = Field(gt=timedelta())
    support_ids: tuple[str, ...] = Field(min_length=1)
    invariant_violations: tuple[InvariantViolation, ...] = ()
    content_hash: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def result_state_is_bound_to_transition(self) -> TwinTransition:
        from_state = TwinState.model_validate(self.from_state.model_dump(mode="json"))
        to_state = TwinState.model_validate(self.to_state.model_dump(mode="json"))
        if self.from_state_id != from_state.state_id:
            raise ValueError("twin transition source state ID must match its bound source state")
        if from_state.twin_id != self.twin_id or to_state.twin_id != self.twin_id:
            raise ValueError("twin transition result state must share twin ID")
        if (
            from_state.domain_pack_id != self.domain_pack_id
            or to_state.domain_pack_id != self.domain_pack_id
        ):
            raise ValueError("twin transition result state must share domain pack")
        if (
            from_state.domain_pack_version != self.domain_pack_version
            or to_state.domain_pack_version != self.domain_pack_version
        ):
            raise ValueError("twin transition result state must share domain pack version")
        if to_state.world_snapshot_hash != from_state.world_snapshot_hash:
            raise ValueError("twin transition states must share one source world snapshot")
        if to_state.as_of != from_state.as_of + self.time_step:
            raise ValueError(
                "twin transition result state must advance exactly one declared time step"
            )
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("twin transition content hash mismatch")
        return self

    def sealed(self) -> TwinTransition:
        """Return the deterministic, content-addressed candidate transition."""
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = TwinTransition.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})
