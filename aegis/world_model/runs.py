"""Sealed, candidate-only scenario-run and engineering-fixture replay contracts."""

from __future__ import annotations

from math import isclose, isfinite
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel

from .ai_infrastructure import CapexToSupplierRevenueTwin, MechanismRegistry
from .contracts import WorldSnapshot
from .contributions import EffectContributionLedger
from .scenario import CompiledScenario
from .twin import TwinTransition


class ScenarioRunManifest(CandidateContractModel):
    """One reproducible candidate simulation invocation; hashes are not authentication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_run_id: str = Field(min_length=1)
    world_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiled_scenario_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mechanism_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    domain_pack_id: str = Field(min_length=1)
    domain_pack_version: str = Field(min_length=1)
    twin_id: str = Field(min_length=1)
    random_seed: int = Field(ge=0)
    code_revision: str = Field(min_length=1)
    created_at: AwareDatetime
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_a_valid_content_hash(self) -> ScenarioRunManifest:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("scenario run manifest content hash mismatch")
        return self

    def sealed(self) -> ScenarioRunManifest:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = ScenarioRunManifest.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class ScenarioRunResult(CandidateContractModel):
    """One sealed candidate outcome, never a price, portfolio, or release decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: ScenarioRunManifest
    compiled_scenario: CompiledScenario
    mechanism_registry: MechanismRegistry
    transition: TwinTransition
    contribution_ledger: EffectContributionLedger
    support_status: Literal["fully_supported", "partially_supported", "stress_only"] = "stress_only"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_sealed_and_bound_to_one_run(self) -> ScenarioRunResult:
        manifest = ScenarioRunManifest.model_validate(self.manifest.model_dump(mode="json"))
        compiled = CompiledScenario.model_validate(self.compiled_scenario.model_dump(mode="json"))
        registry = MechanismRegistry.model_validate(self.mechanism_registry.model_dump(mode="json"))
        transition = TwinTransition.model_validate(self.transition.model_dump(mode="json"))
        snapshot = WorldSnapshot.model_validate(
            transition.from_state.world_snapshot.model_dump(mode="json")
        )
        ledger = EffectContributionLedger.model_validate(
            self.contribution_ledger.model_dump(mode="json")
        )
        if (
            manifest.content_hash is None
            or compiled.content_hash is None
            or registry.content_hash is None
            or transition.content_hash is None
            or ledger.content_hash is None
            or snapshot.content_hash is None
        ):
            raise ValueError(
                "scenario run result requires sealed manifest, compiled scenario, registry, "
                "transition, and ledger"
            )
        if manifest.compiled_scenario_hash != compiled.content_hash:
            raise ValueError("scenario run manifest compiled scenario does not match the result")
        if manifest.mechanism_registry_hash != registry.content_hash:
            raise ValueError("scenario run manifest mechanism registry does not match the result")
        if compiled.world_snapshot_hash != manifest.world_snapshot_hash:
            raise ValueError("scenario run compiled scenario does not match the manifest snapshot")
        if compiled.snapshot_as_of != snapshot.as_of:
            raise ValueError(
                "scenario run compiled scenario cutoff does not match transition snapshot"
            )
        if manifest.twin_id != transition.twin_id:
            raise ValueError("scenario run manifest twin does not match transition")
        if (
            manifest.domain_pack_id != transition.domain_pack_id
            or manifest.domain_pack_version != transition.domain_pack_version
            or registry.domain_pack_id != manifest.domain_pack_id
            or registry.domain_pack_version != manifest.domain_pack_version
        ):
            raise ValueError(
                "scenario run manifest domain does not match the transition and registry"
            )
        if manifest.world_snapshot_hash != transition.from_state.world_snapshot_hash:
            raise ValueError("scenario run manifest snapshot does not match transition")
        if (
            transition.mechanism_registry_hash is None
            or transition.mechanism_registry_hash != registry.content_hash
        ):
            raise ValueError("scenario run mechanism registry does not match transition")
        if manifest.random_seed != snapshot.random_seed:
            raise ValueError("scenario run manifest random seed does not match transition snapshot")
        if manifest.code_revision != snapshot.code_revision:
            raise ValueError(
                "scenario run manifest code revision does not match transition snapshot"
            )
        mechanisms_by_support_id = {
            f"{mechanism.mechanism.mechanism_id}@{mechanism.version}": mechanism
            for mechanism in registry.mechanisms
        }
        if not transition.support_ids or not set(transition.support_ids).issubset(
            mechanisms_by_support_id
        ):
            raise ValueError("scenario run requires registered support IDs")
        selected_mechanisms = tuple(
            mechanisms_by_support_id[support_id] for support_id in transition.support_ids
        )
        if any(
            mechanism.causal_graph_hash != snapshot.causal_graph_hash
            for mechanism in selected_mechanisms
        ):
            raise ValueError(
                "scenario run mechanism causal graph does not match transition snapshot"
            )
        if ledger.simulation_id != manifest.scenario_run_id:
            raise ValueError("scenario run contribution ledger does not match the manifest")
        if self.support_status == "fully_supported" and transition.invariant_violations:
            raise ValueError("fully supported scenario runs require no invariant violations")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("scenario run result content hash mismatch")
        return self

    def sealed(self) -> ScenarioRunResult:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = ScenarioRunResult.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class HistoricalReplayFixture(CandidateContractModel):
    """Local engineering fixture only; it cannot establish empirical release evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str = Field(min_length=1)
    as_of: AwareDatetime
    world_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiled_scenario_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_variable_id: str = Field(min_length=1)
    expected_value: float
    unit: str = Field(min_length=1)
    error_bound: float = Field(ge=0.0)
    fixture_disposition: Literal["engineering_only"] = "engineering_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_engineering_only_and_content_addressed(self) -> HistoricalReplayFixture:
        if not isfinite(self.expected_value) or not isfinite(self.error_bound):
            raise ValueError("historical replay fixture values must be finite")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("historical replay fixture content hash mismatch")
        return self

    def sealed(self) -> HistoricalReplayFixture:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = HistoricalReplayFixture.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class HistoricalReplayEvaluation(CandidateContractModel):
    """Engineering-only local error measurement, explicitly barred from release use."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture: HistoricalReplayFixture
    scenario_run: ScenarioRunResult
    actual_value: float
    absolute_error: float = Field(ge=0.0)
    within_error_bound: bool
    release_disposition: Literal["release_gated"] = "release_gated"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_bound_to_an_engineering_fixture(self) -> HistoricalReplayEvaluation:
        fixture = HistoricalReplayFixture.model_validate(self.fixture.model_dump(mode="json"))
        scenario_run = ScenarioRunResult.model_validate(self.scenario_run.model_dump(mode="json"))
        if fixture.content_hash is None or scenario_run.content_hash is None:
            raise ValueError(
                "historical replay evaluation requires sealed fixture and scenario run"
            )
        if fixture.world_snapshot_hash != scenario_run.manifest.world_snapshot_hash:
            raise ValueError("historical replay fixture does not match the scenario snapshot")
        if fixture.compiled_scenario_hash != scenario_run.manifest.compiled_scenario_hash:
            raise ValueError("historical replay fixture does not match the compiled scenario")
        transition_variables = {
            variable.variable_id: variable
            for variable in scenario_run.transition.to_state.variables
        }
        transition_variable = transition_variables.get(fixture.target_variable_id)
        if transition_variable is None or transition_variable.unit != fixture.unit:
            raise ValueError(
                "historical replay fixture target is missing from the scenario transition"
            )
        if not isclose(self.actual_value, transition_variable.value, abs_tol=1e-12):
            raise ValueError(
                "historical replay actual value does not match the scenario transition"
            )
        if not isfinite(self.actual_value) or not isfinite(self.absolute_error):
            raise ValueError("historical replay evaluation values must be finite")
        if not isclose(
            self.absolute_error, abs(self.actual_value - fixture.expected_value), abs_tol=1e-12
        ):
            raise ValueError("historical replay absolute error must match the fixture result")
        if self.within_error_bound != (self.absolute_error <= fixture.error_bound):
            raise ValueError("historical replay error-bound outcome must match the declared bound")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("historical replay evaluation content hash mismatch")
        return self

    def sealed(self) -> HistoricalReplayEvaluation:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = HistoricalReplayEvaluation.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def run_historical_fixture(
    fixture: HistoricalReplayFixture,
    manifest: ScenarioRunManifest,
    twin: CapexToSupplierRevenueTwin,
    snapshot: WorldSnapshot,
    compiled_scenario: CompiledScenario,
    contribution_ledger: EffectContributionLedger,
) -> HistoricalReplayEvaluation:
    """Run the pure reference twin against one sealed local engineering fixture."""
    validated_fixture = HistoricalReplayFixture.model_validate(fixture.model_dump(mode="json"))
    validated_manifest = ScenarioRunManifest.model_validate(manifest.model_dump(mode="json"))
    validated_snapshot = WorldSnapshot.model_validate(snapshot.model_dump(mode="json"))
    validated_compiled = CompiledScenario.model_validate(compiled_scenario.model_dump(mode="json"))
    validated_ledger = EffectContributionLedger.model_validate(
        contribution_ledger.model_dump(mode="json")
    )
    if (
        validated_fixture.content_hash is None
        or validated_manifest.content_hash is None
        or validated_snapshot.content_hash is None
        or validated_compiled.content_hash is None
        or validated_ledger.content_hash is None
    ):
        raise ValueError("historical fixture runner requires sealed inputs")
    if validated_fixture.as_of != validated_snapshot.as_of:
        raise ValueError("historical replay fixture cutoff does not match the world snapshot")
    if (
        validated_fixture.world_snapshot_hash != validated_snapshot.content_hash
        or validated_manifest.world_snapshot_hash != validated_snapshot.content_hash
    ):
        raise ValueError("historical replay fixture or manifest does not match the world snapshot")
    if (
        validated_fixture.compiled_scenario_hash != validated_compiled.content_hash
        or validated_manifest.compiled_scenario_hash != validated_compiled.content_hash
    ):
        raise ValueError(
            "historical replay fixture or manifest does not match the compiled scenario"
        )
    if validated_manifest.mechanism_registry_hash != twin.mechanism_registry_hash:
        raise ValueError("historical replay manifest does not match the twin mechanism registry")
    transition = twin.transition_compiled(validated_snapshot, validated_compiled)
    run = ScenarioRunResult(
        manifest=validated_manifest,
        compiled_scenario=validated_compiled,
        mechanism_registry=twin.mechanism_registry,
        transition=transition,
        contribution_ledger=validated_ledger,
    ).sealed()
    variables = {variable.variable_id: variable for variable in transition.to_state.variables}
    variable = variables.get(validated_fixture.target_variable_id)
    if variable is None or variable.unit != validated_fixture.unit:
        raise ValueError("historical replay target variable is missing or has an unsupported unit")
    absolute_error = abs(variable.value - validated_fixture.expected_value)
    return HistoricalReplayEvaluation(
        fixture=validated_fixture,
        scenario_run=run,
        actual_value=variable.value,
        absolute_error=absolute_error,
        within_error_bound=absolute_error <= validated_fixture.error_bound,
    ).sealed()
