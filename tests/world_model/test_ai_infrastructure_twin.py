from datetime import UTC, datetime

import pytest

import aegis.world_model as world_model
from aegis.causal import MechanismDefinition
from aegis.world_model.ai_infrastructure import (
    AI_INFRASTRUCTURE_DOMAIN,
    CapexToSupplierRevenueParameters,
    CapexToSupplierRevenueTwin,
    CompiledScenarioTwin,
    MechanismRegistry,
    VersionedMechanism,
)
from aegis.world_model.contracts import (
    ScenarioIntervention,
    VariableProvenance,
    WorldSnapshot,
    WorldVariable,
)
from aegis.world_model.scenario import CompiledScenario, compile_scenario

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def test_ai_infrastructure_slice_is_a_candidate_world_model_public_api() -> None:
    assert world_model.CapexToSupplierRevenueTwin
    assert world_model.MechanismRegistry
    assert isinstance(_twin(), CompiledScenarioTwin)


def _variable(variable_id: str, value: float, unit: str) -> WorldVariable:
    return WorldVariable(
        variable_id=variable_id,
        value=value,
        unit=unit,
        provenance=VariableProvenance.OBSERVED,
        available_at=NOW,
        evidence_ids=("evidence-1",),
        uncertainty_label="observed",
    )


def _snapshot(**updates: object) -> WorldSnapshot:
    values: dict[str, object] = {
        "snapshot_id": "ai-infrastructure-world-1",
        "as_of": NOW,
        "pit_snapshot_hash": "a" * 64,
        "causal_graph_hash": "b" * 64,
        "variables": (
            _variable("hyperscaler.ai_capex", 100.0, "usd_millions"),
            _variable("supplier.revenue", 10.0, "usd_millions"),
            _variable("supplier.cash_from_revenue", 8.0, "usd_millions"),
            _variable("supplier.revenue_capacity", 20.0, "usd_millions"),
        ),
        "random_seed": 7,
        "code_revision": "test-revision",
    }
    values.update(updates)
    return WorldSnapshot(**values).sealed()


def _compiled(snapshot: WorldSnapshot, **updates: object) -> CompiledScenario:
    values: dict[str, object] = {
        "intervention_id": "capex-increase",
        "target_variable_id": "hyperscaler.ai_capex",
        "relative_change": 0.1,
        "starts_at": NOW,
        "rationale": "candidate AI infrastructure stress",
        "assumption_ids": ("capex-pass-through",),
    }
    values.update(updates)
    return compile_scenario(snapshot, (ScenarioIntervention(**values),))


def _mechanism(**updates: object) -> VersionedMechanism:
    values: dict[str, object] = {
        "mechanism": MechanismDefinition(
            mechanism_id="capex-to-supplier-revenue",
            causal_edge_id="capex-to-supplier-revenue-edge",
            domain_pack="ai-infrastructure",
            input_variable_ids=("hyperscaler.ai_capex",),
            output_variable_ids=("supplier.revenue", "supplier.cash_from_revenue"),
            assumption_ids=("capex-pass-through",),
        ),
        "version": "1.0.0",
        "domain_pack_id": "ai-infrastructure",
        "domain_pack_version": "1.0.0",
        "causal_graph_hash": "b" * 64,
        "domain_manifest_hash": AI_INFRASTRUCTURE_DOMAIN.content_hash,
    }
    values.update(updates)
    return VersionedMechanism(**values).sealed()


def _registry(**updates: object) -> MechanismRegistry:
    values: dict[str, object] = {
        "registry_id": "ai-infrastructure-mechanisms",
        "version": "1.0.0",
        "domain_pack_id": "ai-infrastructure",
        "domain_pack_version": "1.0.0",
        "mechanisms": (_mechanism(),),
        "domain_manifest_hash": AI_INFRASTRUCTURE_DOMAIN.content_hash,
    }
    values.update(updates)
    return MechanismRegistry(**values).sealed()


def _twin() -> CapexToSupplierRevenueTwin:
    return CapexToSupplierRevenueTwin(
        CapexToSupplierRevenueParameters(
            parameter_draw_id="draw-7",
            capex_to_revenue_ratio=0.2,
            cash_conversion_ratio=0.8,
        )
    )


def test_capex_twin_creates_a_byte_identical_sealed_candidate_transition() -> None:
    snapshot = _snapshot()
    compiled = _compiled(snapshot)
    registry = _registry()

    first = _twin().transition(snapshot, compiled, registry)
    second = _twin().transition(snapshot, compiled, registry)

    assert AI_INFRASTRUCTURE_DOMAIN.content_hash
    assert first.content_hash
    assert first.model_dump_json() == second.model_dump_json()
    assert first.support_ids == ("capex-to-supplier-revenue@1.0.0",)
    assert first.to_state.domain_pack_version == "1.0.0"
    assert {
        variable.variable_id: variable.value for variable in first.to_state.variables
    } == pytest.approx(
        {
            "hyperscaler.ai_capex": 110.0,
            "supplier.revenue": 12.0,
            "supplier.cash_from_revenue": 9.6,
            "supplier.revenue_capacity": 20.0,
        }
    )
    assert first.invariant_violations == ()


def test_capex_twin_reports_revenue_to_cash_reconciliation_as_an_invariant_violation() -> None:
    transition = _twin().transition(_snapshot(), _compiled(_snapshot()), _registry())
    invalid_state = transition.to_state.model_copy(
        update={
            "state_id": "invalid-revenue-cash-state",
            "variables": tuple(
                variable.model_copy(update={"value": 9.5})
                if variable.variable_id == "supplier.cash_from_revenue"
                else variable
                for variable in transition.to_state.variables
            ),
            "content_hash": None,
        }
    )

    violations = _twin().validate(invalid_state)

    assert len(violations) == 1
    assert violations[0].invariant_id == "revenue-to-cash-reconciliation"
    assert violations[0].affected_variable_ids == (
        "supplier.revenue",
        "supplier.cash_from_revenue",
    )


def test_capex_twin_fails_closed_on_capacity_breach() -> None:
    snapshot = _snapshot(
        variables=(
            _variable("hyperscaler.ai_capex", 100.0, "usd_millions"),
            _variable("supplier.revenue", 10.0, "usd_millions"),
            _variable("supplier.cash_from_revenue", 8.0, "usd_millions"),
            _variable("supplier.revenue_capacity", 11.0, "usd_millions"),
        )
    )

    with pytest.raises(ValueError, match="capacity"):
        _twin().transition(snapshot, _compiled(snapshot), _registry())


def test_capex_twin_rejects_a_source_snapshot_already_above_capacity() -> None:
    snapshot = _snapshot(
        variables=(
            _variable("hyperscaler.ai_capex", 100.0, "usd_millions"),
            _variable("supplier.revenue", 21.0, "usd_millions"),
            _variable("supplier.cash_from_revenue", 16.8, "usd_millions"),
            _variable("supplier.revenue_capacity", 20.0, "usd_millions"),
        )
    )
    compiled = _compiled(snapshot, relative_change=-0.1)

    with pytest.raises(ValueError, match="source revenue capacity"):
        _twin().transition(snapshot, compiled, _registry())


def test_capex_twin_rejects_a_source_snapshot_with_unreconciled_cash() -> None:
    snapshot = _snapshot(
        variables=(
            _variable("hyperscaler.ai_capex", 100.0, "usd_millions"),
            _variable("supplier.revenue", 10.0, "usd_millions"),
            _variable("supplier.cash_from_revenue", 9.0, "usd_millions"),
            _variable("supplier.revenue_capacity", 20.0, "usd_millions"),
        )
    )

    with pytest.raises(ValueError, match="source revenue-to-cash"):
        _twin().transition(snapshot, _compiled(snapshot), _registry())


def test_capex_twin_rejects_a_sealed_unrelated_mechanism() -> None:
    unrelated = _mechanism(
        mechanism=MechanismDefinition(
            mechanism_id="capex-to-supplier-revenue",
            causal_edge_id="unrelated-edge",
            domain_pack="ai-infrastructure",
            input_variable_ids=("unrelated.input",),
            output_variable_ids=("unrelated.output",),
            assumption_ids=("unrelated-assumption",),
        )
    )
    registry = _registry(mechanisms=(unrelated,))
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="mechanism does not bind"):
        _twin().transition(snapshot, _compiled(snapshot), registry)


def test_capex_twin_rejects_a_mechanism_bound_to_another_causal_graph() -> None:
    registry = _registry(mechanisms=(_mechanism(causal_graph_hash="c" * 64),))
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="causal graph"):
        _twin().transition(snapshot, _compiled(snapshot), registry)


def test_mechanism_registry_rejects_a_child_with_a_different_manifest_hash() -> None:
    with pytest.raises(ValueError, match="manifest hash"):
        _registry(mechanisms=(_mechanism(domain_manifest_hash="c" * 64),))


def test_mechanism_registry_resolve_revalidates_a_model_construct_bypass() -> None:
    registry = _registry()
    bypassed = MechanismRegistry.model_construct(
        **{
            **registry.model_dump(),
            "mechanisms": (_mechanism(domain_manifest_hash="c" * 64),),
        }
    )

    with pytest.raises(ValueError, match="manifest hash"):
        bypassed.resolve(
            mechanism_id="capex-to-supplier-revenue",
            mechanism_version="1.0.0",
            domain_pack_id="ai-infrastructure",
            domain_pack_version="1.0.0",
        )


def test_capex_twin_fails_closed_on_unsealed_or_unsupported_inputs() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValueError, match="sealed world snapshot"):
        _twin().transition(
            snapshot.model_copy(update={"content_hash": None}), _compiled(snapshot), _registry()
        )
    with pytest.raises(ValueError, match="sealed compiled intervention"):
        _twin().transition(
            snapshot, _compiled(snapshot).model_copy(update={"content_hash": None}), _registry()
        )

    wrong_unit_snapshot = _snapshot(
        variables=(
            _variable("hyperscaler.ai_capex", 100.0, "usd_millions"),
            _variable("supplier.revenue", 10.0, "usd"),
            _variable("supplier.cash_from_revenue", 8.0, "usd_millions"),
            _variable("supplier.revenue_capacity", 20.0, "usd_millions"),
        )
    )
    with pytest.raises(ValueError, match="unit"):
        _twin().transition(wrong_unit_snapshot, _compiled(wrong_unit_snapshot), _registry())

    version_two_registry = _registry(
        domain_pack_version="2.0.0",
        mechanisms=(_mechanism(domain_pack_version="2.0.0"),),
    )
    with pytest.raises(ValueError, match="domain pack version"):
        _twin().transition(snapshot, _compiled(snapshot), version_two_registry)
    with pytest.raises(ValueError, match="mechanism"):
        _twin().transition(snapshot, _compiled(snapshot), _registry(mechanisms=()))


def test_capex_twin_revalidates_future_and_tampered_mechanism_inputs() -> None:
    future = _variable("supplier.revenue", 10.0, "usd_millions").model_copy(
        update={"available_at": datetime(2024, 2, 1, tzinfo=UTC)}
    )
    snapshot = _snapshot()
    future_payload = snapshot.model_dump()
    future_payload["variables"] = (
        snapshot.variables[0],
        future,
        snapshot.variables[2],
        snapshot.variables[3],
    )
    future_snapshot = WorldSnapshot.model_construct(**future_payload)
    with pytest.raises(ValueError, match="future"):
        _twin().transition(future_snapshot, _compiled(snapshot), _registry())

    mechanism = _mechanism()
    mechanism_payload = mechanism.model_dump()
    mechanism_payload["mechanism"] = mechanism.mechanism
    mechanism_payload["content_hash"] = "c" * 64
    tampered_mechanism = VersionedMechanism.model_construct(**mechanism_payload)
    tampered_registry = MechanismRegistry.model_construct(
        registry_id="ai-infrastructure-mechanisms",
        version="1.0.0",
        domain_pack_id="ai-infrastructure",
        domain_pack_version="1.0.0",
        mechanisms=(tampered_mechanism,),
        authority="candidate_only",
        content_hash="d" * 64,
    )
    with pytest.raises(ValueError, match="mechanism content hash mismatch"):
        _twin().transition(snapshot, _compiled(snapshot), tampered_registry)
