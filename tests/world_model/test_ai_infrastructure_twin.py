from datetime import UTC, datetime, timedelta

import pytest

import aegis.world_model as world_model
from aegis.causal import MechanismDefinition
from aegis.world_model.ai_infrastructure import (
    AI_INFRASTRUCTURE_DOMAIN,
    CapexToSupplierRevenueParameters,
    CapexToSupplierRevenueTwin,
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
    assert isinstance(_twin(), world_model.DigitalTwin)


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
            _variable("hyperscaler.ai_capex_growth", 0.2, "ratio"),
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
        "target_variable_id": "hyperscaler.ai_capex_growth",
        "absolute_change": 0.1,
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
            input_variable_ids=("hyperscaler.ai_capex_growth",),
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


def _twin(registry: MechanismRegistry | None = None) -> CapexToSupplierRevenueTwin:
    return CapexToSupplierRevenueTwin(
        CapexToSupplierRevenueParameters(
            parameter_draw_id="draw-7",
            capex_growth_to_revenue_elasticity=0.2,
            cash_conversion_ratio=0.8,
        ),
        registry if registry is not None else _registry(),
    )


def test_capex_twin_creates_a_byte_identical_sealed_candidate_transition() -> None:
    snapshot = _snapshot()
    compiled = _compiled(snapshot)
    registry = _registry()

    first = _twin(registry).transition_compiled(snapshot, compiled)
    second = _twin(registry).transition_compiled(snapshot, compiled)

    assert AI_INFRASTRUCTURE_DOMAIN.content_hash
    assert first.content_hash
    assert first.model_dump_json() == second.model_dump_json()
    assert first.support_ids == ("capex-to-supplier-revenue@1.0.0",)
    assert first.to_state.domain_pack_version == "1.0.0"
    assert {
        variable.variable_id: variable.value for variable in first.to_state.variables
    } == pytest.approx(
        {
            "hyperscaler.ai_capex_growth": 0.3,
            "supplier.revenue": 10.2,
            "supplier.cash_from_revenue": 8.16,
            "supplier.revenue_capacity": 20.0,
        }
    )
    assert first.invariant_violations == ()


def test_capex_twin_transition_applies_a_bound_input_from_a_valid_state() -> None:
    snapshot = _snapshot()
    source = _twin().initial_state(snapshot)

    transition = _twin().transition(
        source,
        {"hyperscaler.ai_capex_growth": 0.3},
        "draw-7",
        timedelta(days=30),
    )

    assert transition.to_state.variables[0].value == pytest.approx(0.3)
    assert transition.to_state.variables[1].value == pytest.approx(10.2)


def test_capex_twin_transition_rejects_a_forged_initial_state() -> None:
    snapshot = _snapshot()
    source = _twin().initial_state(snapshot)
    forged = source.model_copy(
        update={
            "variables": tuple(
                variable.model_copy(update={"value": 15.0})
                if variable.variable_id == "supplier.revenue"
                else variable.model_copy(update={"value": 12.0})
                if variable.variable_id == "supplier.cash_from_revenue"
                else variable
                for variable in source.variables
            ),
            "content_hash": None,
        }
    ).sealed()

    with pytest.raises(ValueError, match="initial state"):
        _twin().transition(
            forged,
            {"hyperscaler.ai_capex_growth": 0.3},
            "draw-7",
            timedelta(days=30),
        )


def test_capex_twin_allows_a_bounded_negative_post_intervention_growth_rate() -> None:
    snapshot = _snapshot(
        variables=(
            _variable("hyperscaler.ai_capex_growth", 0.1, "ratio"),
            _variable("supplier.revenue", 10.0, "usd_millions"),
            _variable("supplier.cash_from_revenue", 8.0, "usd_millions"),
            _variable("supplier.revenue_capacity", 20.0, "usd_millions"),
        )
    )

    transition = _twin().transition_compiled(snapshot, _compiled(snapshot, absolute_change=-0.2))

    assert transition.to_state.variables[0].value == pytest.approx(-0.1)


def test_capex_twin_reports_revenue_to_cash_reconciliation_as_an_invariant_violation() -> None:
    transition = _twin().transition_compiled(_snapshot(), _compiled(_snapshot()))
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
    ).sealed()

    violations = _twin().validate(invalid_state)

    assert len(violations) == 1
    assert violations[0].invariant_id == "revenue-to-cash-reconciliation"
    assert violations[0].affected_variable_ids == (
        "supplier.revenue",
        "supplier.cash_from_revenue",
    )


def test_capex_twin_rejects_a_foreign_state_from_all_public_state_consumers() -> None:
    transition = _twin().transition_compiled(_snapshot(), _compiled(_snapshot()))
    foreign_state = transition.to_state.model_copy(
        update={"twin_id": "foreign-twin", "content_hash": None}
    ).sealed()

    with pytest.raises(ValueError, match="twin state"):
        _twin().observe(foreign_state)
    with pytest.raises(ValueError, match="twin state"):
        _twin().validate(foreign_state)


@pytest.mark.parametrize(
    ("update", "message"),
    (
        ({"content_hash": None}, "sealed"),
        ({"domain_pack_id": "other-domain", "content_hash": None}, "twin state"),
        ({"domain_pack_version": "2.0.0", "content_hash": None}, "twin state"),
    ),
)
def test_capex_twin_rejects_unsealed_or_wrong_domain_state_consumers(
    update: dict[str, str | None], message: str
) -> None:
    transition = _twin().transition_compiled(_snapshot(), _compiled(_snapshot()))
    state = transition.to_state.model_copy(update=update)
    if state.content_hash is None and update != {"content_hash": None}:
        state = state.sealed()

    with pytest.raises(ValueError, match=message):
        _twin().observe(state)
    with pytest.raises(ValueError, match=message):
        _twin().validate(state)


def test_capex_twin_fails_closed_on_capacity_breach() -> None:
    snapshot = _snapshot(
        variables=(
            _variable("hyperscaler.ai_capex_growth", 0.2, "ratio"),
            _variable("supplier.revenue", 10.0, "usd_millions"),
            _variable("supplier.cash_from_revenue", 8.0, "usd_millions"),
            _variable("supplier.revenue_capacity", 10.1, "usd_millions"),
        )
    )

    with pytest.raises(ValueError, match="capacity"):
        _twin().transition_compiled(snapshot, _compiled(snapshot))


def test_capex_twin_rejects_a_source_snapshot_already_above_capacity() -> None:
    snapshot = _snapshot(
        variables=(
            _variable("hyperscaler.ai_capex_growth", 0.2, "ratio"),
            _variable("supplier.revenue", 21.0, "usd_millions"),
            _variable("supplier.cash_from_revenue", 16.8, "usd_millions"),
            _variable("supplier.revenue_capacity", 20.0, "usd_millions"),
        )
    )
    compiled = _compiled(snapshot, absolute_change=-0.1)

    with pytest.raises(ValueError, match="source revenue capacity"):
        _twin().transition_compiled(snapshot, compiled)


def test_capex_twin_rejects_a_source_snapshot_with_unreconciled_cash() -> None:
    snapshot = _snapshot(
        variables=(
            _variable("hyperscaler.ai_capex_growth", 0.2, "ratio"),
            _variable("supplier.revenue", 10.0, "usd_millions"),
            _variable("supplier.cash_from_revenue", 9.0, "usd_millions"),
            _variable("supplier.revenue_capacity", 20.0, "usd_millions"),
        )
    )

    with pytest.raises(ValueError, match="source revenue-to-cash"):
        _twin().transition_compiled(snapshot, _compiled(snapshot))


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
        _twin(registry).transition_compiled(snapshot, _compiled(snapshot))


def test_capex_twin_rejects_a_mechanism_bound_to_another_causal_graph() -> None:
    registry = _registry(mechanisms=(_mechanism(causal_graph_hash="c" * 64),))
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="causal graph"):
        _twin(registry).transition_compiled(snapshot, _compiled(snapshot))


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
        _twin().transition_compiled(
            snapshot.model_copy(update={"content_hash": None}), _compiled(snapshot)
        )
    with pytest.raises(ValueError, match="sealed compiled intervention"):
        _twin().transition_compiled(
            snapshot, _compiled(snapshot).model_copy(update={"content_hash": None})
        )

    wrong_unit_snapshot = _snapshot(
        variables=(
            _variable("hyperscaler.ai_capex_growth", 0.2, "ratio"),
            _variable("supplier.revenue", 10.0, "usd"),
            _variable("supplier.cash_from_revenue", 8.0, "usd_millions"),
            _variable("supplier.revenue_capacity", 20.0, "usd_millions"),
        )
    )
    with pytest.raises(ValueError, match="unit"):
        _twin().transition_compiled(wrong_unit_snapshot, _compiled(wrong_unit_snapshot))

    version_two_registry = _registry(
        domain_pack_version="2.0.0",
        mechanisms=(_mechanism(domain_pack_version="2.0.0"),),
    )
    with pytest.raises(ValueError, match="domain pack version"):
        _twin(version_two_registry).transition_compiled(snapshot, _compiled(snapshot))
    with pytest.raises(ValueError, match="mechanism"):
        _twin(_registry(mechanisms=())).transition_compiled(snapshot, _compiled(snapshot))


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
        _twin().transition_compiled(future_snapshot, _compiled(snapshot))

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
        _twin(tampered_registry).transition_compiled(snapshot, _compiled(snapshot))
