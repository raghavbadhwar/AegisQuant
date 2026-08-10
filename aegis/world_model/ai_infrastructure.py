"""One deterministic, candidate-only AI-infrastructure business-clock twin.

Monetary variables use ``usd_millions`` per fixed 30-day business step;
``hyperscaler.ai_capex_growth`` uses the dimensionless ``ratio`` unit.
The bounded elasticity and cash-conversion ratio are candidate parameters, never
pricing, portfolio, promotion, or execution inputs.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from math import isclose, isfinite
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from aegis.causal import MechanismDefinition
from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel

from .contracts import ScenarioIntervention, VariableProvenance, WorldSnapshot, WorldVariable
from .domain_pack import DomainPackManifest, DomainPackStatus
from .scenario import CompiledScenario
from .twin import InvariantViolation, TwinState, TwinTransition

DOMAIN_PACK_ID: Literal["ai-infrastructure"] = "ai-infrastructure"
DOMAIN_PACK_VERSION: Literal["1.0.0"] = "1.0.0"
REGISTRY_VERSION: Literal["1.0.0"] = "1.0.0"
MECHANISM_ID: Literal["capex-to-supplier-revenue"] = "capex-to-supplier-revenue"
MECHANISM_VERSION: Literal["1.0.0"] = "1.0.0"
TWIN_ID = "capex-to-supplier-revenue-twin"
BUSINESS_TIME_STEP = timedelta(days=30)
ACCOUNTING_TOLERANCE_USD_MILLIONS = 0.000001

CAPEX_GROWTH_VARIABLE = "hyperscaler.ai_capex_growth"
REVENUE_VARIABLE = "supplier.revenue"
CASH_FROM_REVENUE_VARIABLE = "supplier.cash_from_revenue"
REVENUE_CAPACITY_VARIABLE = "supplier.revenue_capacity"
CAPEX_GROWTH_MIN = -1.0
CAPEX_GROWTH_MAX = 1.0
_VARIABLE_UNITS = {
    CAPEX_GROWTH_VARIABLE: "ratio",
    REVENUE_VARIABLE: "usd_millions",
    CASH_FROM_REVENUE_VARIABLE: "usd_millions",
    REVENUE_CAPACITY_VARIABLE: "usd_millions",
}
_STABLE_ID = r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$"
_SHA256 = r"^[0-9a-f]{64}$"


AI_INFRASTRUCTURE_DOMAIN = DomainPackManifest(
    domain_pack_id=DOMAIN_PACK_ID,
    version=DOMAIN_PACK_VERSION,
    description="Candidate-only 30-day capex-to-supplier-revenue transmission slice.",
    supported_entities=("hyperscaler", "supplier"),
    supported_variables=tuple(_VARIABLE_UNITS),
    supported_interventions=("relative_change", "absolute_change"),
    supported_horizons=("30_day_business_step",),
    twin_ids=(TWIN_ID,),
    mechanism_model_ids=(MECHANISM_ID,),
    validation_report_id="ai-infrastructure-v4b-candidate",
    coverage_limits=("One capex-to-revenue pathway; no market or portfolio effects.",),
    known_failure_modes=("Capacity breach fails closed; no mechanism substitution.",),
    licence_metadata=("Internal candidate-only implementation.",),
    status=DomainPackStatus.CANDIDATE,
).sealed()


class VersionedMechanism(CandidateContractModel):
    """One sealed, candidate-only mechanism bound to a precise domain version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mechanism: MechanismDefinition
    version: str = Field(min_length=1)
    domain_pack_id: str = Field(pattern=_STABLE_ID)
    domain_pack_version: str = Field(min_length=1)
    causal_graph_hash: str = Field(pattern=_SHA256)
    domain_manifest_hash: str = Field(pattern=_SHA256)
    content_hash: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def is_domain_bound_and_hash_valid(self) -> VersionedMechanism:
        mechanism = MechanismDefinition.model_validate(self.mechanism.model_dump(mode="json"))
        if mechanism.domain_pack != self.domain_pack_id:
            raise ValueError("mechanism domain pack must match its versioned binding")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("versioned mechanism content hash mismatch")
        return self

    def sealed(self) -> VersionedMechanism:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        return self.model_copy(update={"content_hash": canonical_sha256(payload)})


class MechanismRegistry(CandidateContractModel):
    """Sealed lookup of candidate mechanisms; it has no promotion authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_id: str = Field(pattern=_STABLE_ID)
    version: str = Field(min_length=1)
    domain_pack_id: str = Field(pattern=_STABLE_ID)
    domain_pack_version: str = Field(min_length=1)
    domain_manifest_hash: str = Field(pattern=_SHA256)
    mechanisms: tuple[VersionedMechanism, ...] = ()
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def is_sealed_and_unique(self) -> MechanismRegistry:
        mechanisms = tuple(
            VersionedMechanism.model_validate(mechanism.model_dump(mode="json"))
            for mechanism in self.mechanisms
        )
        if any(mechanism.content_hash is None for mechanism in mechanisms):
            raise ValueError("mechanism registry requires sealed mechanisms")
        identifiers = [(item.mechanism.mechanism_id, item.version) for item in mechanisms]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("mechanism registry mechanism versions must be unique")
        if any(
            item.domain_pack_id != self.domain_pack_id
            or item.domain_pack_version != self.domain_pack_version
            for item in mechanisms
        ):
            raise ValueError("mechanism registry mechanisms must share its domain pack version")
        if any(item.domain_manifest_hash != self.domain_manifest_hash for item in mechanisms):
            raise ValueError("mechanism registry mechanisms must share its domain manifest hash")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("mechanism registry content hash mismatch")
        return self

    def sealed(self) -> MechanismRegistry:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        return self.model_copy(update={"content_hash": canonical_sha256(payload)})

    def resolve(
        self,
        *,
        mechanism_id: str,
        mechanism_version: str,
        domain_pack_id: str,
        domain_pack_version: str,
    ) -> VersionedMechanism:
        registry = _validated_sealed_registry(self)
        if (
            registry.domain_pack_id != domain_pack_id
            or registry.domain_pack_version != domain_pack_version
        ):
            raise ValueError("mechanism registry domain pack version does not match twin")
        matches = tuple(
            item
            for item in registry.mechanisms
            if item.mechanism.mechanism_id == mechanism_id and item.version == mechanism_version
        )
        if len(matches) != 1:
            raise ValueError("required versioned mechanism is missing from the sealed registry")
        return matches[0]


class CapexToSupplierRevenueParameters(CandidateContractModel):
    """Bounded candidate draw: ratios are dimensionless; money is usd_millions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_draw_id: str = Field(pattern=_STABLE_ID)
    capex_growth_to_revenue_elasticity: float = Field(ge=0.0, le=1.0)
    cash_conversion_ratio: float = Field(ge=0.0, le=1.0)
    domain_pack_id: Literal["ai-infrastructure"] = DOMAIN_PACK_ID
    domain_pack_version: Literal["1.0.0"] = DOMAIN_PACK_VERSION
    registry_version: Literal["1.0.0"] = REGISTRY_VERSION
    mechanism_id: Literal["capex-to-supplier-revenue"] = MECHANISM_ID
    mechanism_version: Literal["1.0.0"] = MECHANISM_VERSION

    @model_validator(mode="after")
    def ratios_are_finite(self) -> CapexToSupplierRevenueParameters:
        if not all(
            isfinite(value)
            for value in (self.capex_growth_to_revenue_elasticity, self.cash_conversion_ratio)
        ):
            raise ValueError("candidate mechanism parameters must be finite")
        return self


class CapexToSupplierRevenueTwin:
    """Pure 30-day candidate twin with capex growth bounded to [-1.0, 1.0]."""

    twin_id = TWIN_ID

    def __init__(
        self,
        parameters: CapexToSupplierRevenueParameters,
        mechanism_registry: MechanismRegistry,
    ) -> None:
        self._parameters = CapexToSupplierRevenueParameters.model_validate(
            parameters.model_dump(mode="json")
        )
        self._mechanism_registry = _validated_sealed_registry(mechanism_registry)

    def initial_state(self, snapshot: WorldSnapshot) -> TwinState:
        """Create the deterministic PIT-safe source state from one sealed snapshot."""
        snapshot, snapshot_hash = _validated_sealed_snapshot(snapshot)
        variables = _validated_domain_variables(snapshot.variables)
        self._validate_source_invariants(variables)
        if AI_INFRASTRUCTURE_DOMAIN.content_hash is None:
            raise ValueError("AI-infrastructure domain definition must be sealed")
        return TwinState(
            state_id=f"{TWIN_ID}:{snapshot.snapshot_id}:initial",
            twin_id=TWIN_ID,
            domain_pack_id=DOMAIN_PACK_ID,
            domain_pack_version=DOMAIN_PACK_VERSION,
            world_snapshot_hash=snapshot_hash,
            world_snapshot=snapshot,
            as_of=snapshot.as_of,
            variables=tuple(variables[variable_id] for variable_id in _VARIABLE_UNITS),
        ).sealed()

    def transition(
        self,
        state: TwinState,
        inputs: Mapping[str, float],
        parameter_draw_id: str,
        time_step: timedelta,
    ) -> TwinTransition:
        """Apply one bounded input through this twin's sealed mechanism registry."""
        source = _validated_twin_state(state)
        snapshot, snapshot_hash = _validated_sealed_snapshot(source.world_snapshot)
        if parameter_draw_id != self._parameters.parameter_draw_id:
            raise ValueError("twin transition parameter draw does not match the bound parameters")
        if time_step != BUSINESS_TIME_STEP:
            raise ValueError("AI-infrastructure twin requires its fixed 30-day business step")
        if (
            source.state_id != f"{TWIN_ID}:{snapshot.snapshot_id}:initial"
            or source.as_of != snapshot.as_of
        ):
            raise ValueError(
                "AI-infrastructure twin only supports one transition from its initial state"
            )
        if source.content_hash != self.initial_state(snapshot).content_hash:
            raise ValueError("twin transition source does not match the canonical initial state")
        capex_growth = _validated_transition_input(inputs)
        registry = _validated_sealed_registry(self._mechanism_registry)
        mechanism = registry.resolve(
            mechanism_id=self._parameters.mechanism_id,
            mechanism_version=self._parameters.mechanism_version,
            domain_pack_id=self._parameters.domain_pack_id,
            domain_pack_version=self._parameters.domain_pack_version,
        )
        self._validate_mechanism_binding(mechanism)
        self._validate_manifest_and_graph_binding(registry, mechanism, snapshot)
        if mechanism.domain_pack_version != self._parameters.domain_pack_version:
            raise ValueError("mechanism versioned domain pack does not match twin")
        if registry.version != self._parameters.registry_version:
            raise ValueError("mechanism registry version does not match twin parameters")
        variables = _validated_domain_variables(source.variables)
        self._validate_source_invariants(variables)
        revenue = variables[REVENUE_VARIABLE].value * (
            1
            + (capex_growth - variables[CAPEX_GROWTH_VARIABLE].value)
            * self._parameters.capex_growth_to_revenue_elasticity
        )
        if not isfinite(revenue) or revenue < 0:
            raise ValueError("supplier revenue must remain finite and nonnegative")
        if revenue > variables[REVENUE_CAPACITY_VARIABLE].value:
            raise ValueError("supplier revenue capacity breach")
        cash_from_revenue = revenue * self._parameters.cash_conversion_ratio
        if not isfinite(cash_from_revenue) or cash_from_revenue < 0:
            raise ValueError("supplier cash from revenue must remain finite and nonnegative")
        target = TwinState(
            state_id=f"{TWIN_ID}:{snapshot.snapshot_id}:step-1",
            twin_id=TWIN_ID,
            domain_pack_id=DOMAIN_PACK_ID,
            domain_pack_version=DOMAIN_PACK_VERSION,
            world_snapshot_hash=snapshot_hash,
            world_snapshot=snapshot,
            as_of=snapshot.as_of + BUSINESS_TIME_STEP,
            variables=(
                _scenario_variable(variables[CAPEX_GROWTH_VARIABLE], capex_growth),
                _estimated_variable(variables[REVENUE_VARIABLE], revenue),
                _estimated_variable(variables[CASH_FROM_REVENUE_VARIABLE], cash_from_revenue),
                variables[REVENUE_CAPACITY_VARIABLE],
            ),
        ).sealed()
        return TwinTransition(
            transition_id=f"{TWIN_ID}:{snapshot.snapshot_id}:step-1",
            twin_id=TWIN_ID,
            domain_pack_id=DOMAIN_PACK_ID,
            domain_pack_version=DOMAIN_PACK_VERSION,
            from_state_id=source.state_id,
            from_state=source,
            to_state=target,
            parameter_draw_id=self._parameters.parameter_draw_id,
            time_step=BUSINESS_TIME_STEP,
            support_ids=(f"{mechanism.mechanism.mechanism_id}@{mechanism.version}",),
            invariant_violations=self.validate(target),
        ).sealed()

    def transition_compiled(
        self,
        snapshot: WorldSnapshot,
        compiled_intervention: CompiledScenario,
    ) -> TwinTransition:
        """Apply exactly one compiled capex intervention without I/O or fallback models."""
        snapshot, _ = _validated_sealed_snapshot(snapshot)
        compiled = _validated_compiled_intervention(compiled_intervention, snapshot)
        source = self.initial_state(snapshot)
        variables = _validated_domain_variables(source.variables)
        intervention = compiled.interventions[0]
        capex_growth = _intervened_capex_growth(
            variables[CAPEX_GROWTH_VARIABLE].value, intervention
        )
        return self.transition(
            source,
            {CAPEX_GROWTH_VARIABLE: capex_growth},
            self._parameters.parameter_draw_id,
            BUSINESS_TIME_STEP,
        )

    def observe(self, state: TwinState) -> dict[str, float]:
        """Return this slice's canonical candidate variables only."""
        state = _validated_twin_state(state)
        variables = _validated_domain_variables(state.variables)
        return {variable_id: variables[variable_id].value for variable_id in _VARIABLE_UNITS}

    def validate(self, state: TwinState) -> tuple[InvariantViolation, ...]:
        """Report the period revenue-to-cash accounting reconciliation explicitly."""
        state = _validated_twin_state(state)
        variables = _validated_domain_variables(state.variables)
        expected_cash = variables[REVENUE_VARIABLE].value * self._parameters.cash_conversion_ratio
        actual_cash = variables[CASH_FROM_REVENUE_VARIABLE].value
        if isclose(
            actual_cash,
            expected_cash,
            rel_tol=0.0,
            abs_tol=ACCOUNTING_TOLERANCE_USD_MILLIONS,
        ):
            return ()
        return (
            InvariantViolation(
                violation_id=f"revenue-to-cash:{state.state_id}",
                invariant_id="revenue-to-cash-reconciliation",
                twin_id=TWIN_ID,
                state_id=state.state_id,
                severity="error",
                message=(
                    "supplier cash from revenue does not reconcile to revenue times cash conversion"
                ),
                affected_variable_ids=(REVENUE_VARIABLE, CASH_FROM_REVENUE_VARIABLE),
            ),
        )

    def _validate_source_invariants(self, variables: dict[str, WorldVariable]) -> None:
        if variables[REVENUE_VARIABLE].value > variables[REVENUE_CAPACITY_VARIABLE].value:
            raise ValueError("source revenue capacity breach")
        expected_cash = variables[REVENUE_VARIABLE].value * self._parameters.cash_conversion_ratio
        if not isclose(
            variables[CASH_FROM_REVENUE_VARIABLE].value,
            expected_cash,
            rel_tol=0.0,
            abs_tol=ACCOUNTING_TOLERANCE_USD_MILLIONS,
        ):
            raise ValueError("source revenue-to-cash reconciliation fails")

    @staticmethod
    def _validate_mechanism_binding(mechanism: VersionedMechanism) -> None:
        definition = mechanism.mechanism
        if (
            definition.causal_edge_id != "capex-to-supplier-revenue-edge"
            or definition.input_variable_ids != (CAPEX_GROWTH_VARIABLE,)
            or definition.output_variable_ids != (REVENUE_VARIABLE, CASH_FROM_REVENUE_VARIABLE)
            or definition.assumption_ids != ("capex-pass-through",)
        ):
            raise ValueError("mechanism does not bind the capex-to-supplier-revenue calculation")

    @staticmethod
    def _validate_manifest_and_graph_binding(
        registry: MechanismRegistry, mechanism: VersionedMechanism, snapshot: WorldSnapshot
    ) -> None:
        manifest_hash = AI_INFRASTRUCTURE_DOMAIN.content_hash
        if manifest_hash is None:
            raise ValueError("AI-infrastructure domain definition must be sealed")
        if (
            registry.domain_manifest_hash != manifest_hash
            or mechanism.domain_manifest_hash != manifest_hash
        ):
            raise ValueError("mechanism registry does not bind the AI-infrastructure manifest")
        if mechanism.causal_graph_hash != snapshot.causal_graph_hash:
            raise ValueError("mechanism does not bind the world snapshot causal graph")


def _validated_sealed_snapshot(snapshot: WorldSnapshot) -> tuple[WorldSnapshot, str]:
    if snapshot.content_hash is None:
        raise ValueError("twin requires a sealed world snapshot")
    validated = WorldSnapshot.model_validate(snapshot.model_dump(mode="json"))
    if validated.content_hash is None:
        raise ValueError("twin requires a sealed world snapshot")
    return validated, validated.content_hash


def _validated_twin_state(state: TwinState) -> TwinState:
    if state.content_hash is None:
        raise ValueError("twin state must be sealed")
    validated = TwinState.model_validate(state.model_dump(mode="json"))
    if (
        validated.twin_id != TWIN_ID
        or validated.domain_pack_id != DOMAIN_PACK_ID
        or validated.domain_pack_version != DOMAIN_PACK_VERSION
    ):
        raise ValueError("twin state does not belong to this AI-infrastructure twin")
    return validated


def _validated_sealed_registry(registry: MechanismRegistry) -> MechanismRegistry:
    if registry.content_hash is None:
        raise ValueError("twin requires a sealed mechanism registry")
    return MechanismRegistry.model_validate(registry.model_dump(mode="json"))


def _validated_compiled_intervention(
    compiled_intervention: CompiledScenario, snapshot: WorldSnapshot
) -> CompiledScenario:
    if compiled_intervention.content_hash is None:
        raise ValueError("twin requires a sealed compiled intervention")
    compiled = CompiledScenario.model_validate(compiled_intervention.model_dump(mode="json"))
    if (
        compiled.world_snapshot_hash != snapshot.content_hash
        or compiled.snapshot_as_of != snapshot.as_of
    ):
        raise ValueError("compiled intervention does not match the sealed world snapshot")
    if len(compiled.interventions) != 1:
        raise ValueError("twin requires exactly one compiled intervention")
    intervention = compiled.interventions[0]
    if intervention.target_variable_id != CAPEX_GROWTH_VARIABLE:
        raise ValueError("compiled intervention targets an unsupported variable")
    if intervention.starts_at != snapshot.as_of:
        raise ValueError("compiled intervention must start at the world snapshot cutoff")
    change = (
        intervention.relative_change
        if intervention.relative_change is not None
        else intervention.absolute_change
    )
    if change is None or not isfinite(change):
        raise ValueError("compiled intervention change must be finite")
    return compiled


def _validated_domain_variables(variables: tuple[WorldVariable, ...]) -> dict[str, WorldVariable]:
    by_id = {variable.variable_id: variable for variable in variables}
    if set(by_id) != set(_VARIABLE_UNITS) or len(by_id) != len(variables):
        raise ValueError("AI-infrastructure twin received unsupported or missing variables")
    for variable_id, unit in _VARIABLE_UNITS.items():
        variable = WorldVariable.model_validate(by_id[variable_id].model_dump(mode="json"))
        if variable.unit != unit:
            raise ValueError(f"AI-infrastructure variable {variable_id} has an unsupported unit")
        if variable_id == CAPEX_GROWTH_VARIABLE:
            _validated_capex_growth(variable.value)
        elif not isfinite(variable.value) or variable.value < 0:
            raise ValueError(
                f"AI-infrastructure variable {variable_id} must be finite and nonnegative"
            )
        by_id[variable_id] = variable
    return by_id


def _intervened_capex_growth(value: float, intervention: ScenarioIntervention) -> float:
    if intervention.relative_change is not None:
        result = value * (1 + intervention.relative_change)
    elif intervention.absolute_change is not None:
        result = value + intervention.absolute_change
    else:
        raise ValueError("compiled intervention must declare one change")
    return _validated_capex_growth(result)


def _validated_transition_input(inputs: Mapping[str, float]) -> float:
    if set(inputs) != {CAPEX_GROWTH_VARIABLE}:
        raise ValueError("AI-infrastructure twin received unsupported or missing transition inputs")
    value = inputs[CAPEX_GROWTH_VARIABLE]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("AI-infrastructure capex growth input must be a finite number")
    return _validated_capex_growth(float(value))


def _validated_capex_growth(value: float) -> float:
    if not isfinite(value) or not CAPEX_GROWTH_MIN <= value <= CAPEX_GROWTH_MAX:
        raise ValueError("capex growth must be finite and within the candidate range [-1.0, 1.0]")
    return value


def _scenario_variable(variable: WorldVariable, value: float) -> WorldVariable:
    return variable.model_copy(
        update={
            "value": value,
            "provenance": VariableProvenance.STRESS_ASSUMPTION,
            "evidence_ids": (),
            "uncertainty_label": "scenario-assumption",
        }
    )


def _estimated_variable(variable: WorldVariable, value: float) -> WorldVariable:
    return variable.model_copy(
        update={
            "value": value,
            "provenance": VariableProvenance.ESTIMATED,
            "evidence_ids": (),
            "uncertainty_label": "candidate-mechanism",
        }
    )
