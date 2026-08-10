from datetime import UTC, datetime

import pytest

from aegis.causal import MechanismDefinition
from aegis.world_model.ai_infrastructure import (
    AI_INFRASTRUCTURE_DOMAIN,
    MechanismRegistry,
    VersionedMechanism,
)
from aegis.world_model.contracts import VariableProvenance, WorldSnapshot, WorldVariable
from aegis.world_model.contributions import EffectContribution
from aegis.world_model.propagation import (
    FeedbackConvergencePolicy,
    FeedbackRule,
    FeedbackSolveResult,
    FeedbackVariable,
    NetworkPropagationEdge,
    NetworkPropagationPlan,
    propagate_effect,
    solve_feedback,
)

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def _edge(**updates: object) -> NetworkPropagationEdge:
    values: dict[str, object] = {
        "edge_id": "capex-to-demand",
        "source_variable_id": "hyperscaler.ai_capex_growth",
        "source_unit": "ratio",
        "target_variable_id": "accelerator.demand_growth",
        "target_unit": "ratio",
        "multiplier": 0.5,
        "lag_steps": 1,
        "mechanism_model_id": "capex-to-demand-v1",
        "path_id": "capex-to-demand",
        "assumption_ids": ("capex-pass-through",),
    }
    values.update(updates)
    return NetworkPropagationEdge(**values).sealed()


def _plan(**updates: object) -> NetworkPropagationPlan:
    snapshot = _snapshot()
    values: dict[str, object] = {
        "plan_id": "ai-infrastructure-network-v1",
        "domain_pack_id": "ai-infrastructure",
        "domain_pack_version": "1.0.0",
        "world_snapshot_hash": snapshot.content_hash,
        "world_snapshot": snapshot,
        "edges": (
            _edge(),
            _edge(
                edge_id="demand-to-supplier",
                source_variable_id="accelerator.demand_growth",
                target_variable_id="supplier.revenue_growth",
                multiplier=2.0,
                lag_steps=2,
                mechanism_model_id="demand-to-supplier-v1",
                path_id="demand-to-supplier",
                assumption_ids=("supplier-exposure",),
            ),
        ),
    }
    values.update(updates)
    if "mechanism_registry" not in updates:
        values["mechanism_registry"] = _registry(values["edges"])
    return NetworkPropagationPlan(**values).sealed()


def _snapshot() -> WorldSnapshot:
    return WorldSnapshot(
        snapshot_id="ai-infrastructure-network-fixture",
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
                evidence_ids=("fixture-evidence",),
                uncertainty_label="engineering-fixture",
            ),
        ),
        random_seed=7,
        code_revision="test-revision",
    ).sealed()


def _registry(edges: object, *, causal_graph_hash: str = "b" * 64) -> MechanismRegistry:
    mechanisms = tuple(
        VersionedMechanism(
            mechanism=MechanismDefinition(
                mechanism_id=edge.mechanism_model_id,
                causal_edge_id=f"{edge.edge_id}-causal-edge",
                domain_pack="ai-infrastructure",
                input_variable_ids=(edge.source_variable_id,),
                output_variable_ids=(edge.target_variable_id,),
                assumption_ids=edge.assumption_ids,
            ),
            version="1.0.0",
            domain_pack_id="ai-infrastructure",
            domain_pack_version="1.0.0",
            causal_graph_hash=causal_graph_hash,
            domain_manifest_hash=AI_INFRASTRUCTURE_DOMAIN.content_hash,
        ).sealed()
        for edge in edges
    )
    return MechanismRegistry(
        registry_id="ai-infrastructure-network-mechanisms",
        version="1.0.0",
        domain_pack_id="ai-infrastructure",
        domain_pack_version="1.0.0",
        domain_manifest_hash=AI_INFRASTRUCTURE_DOMAIN.content_hash,
        mechanisms=mechanisms,
    ).sealed()


def _root_effect() -> EffectContribution:
    return EffectContribution(
        contribution_id="capex-shock",
        simulation_id="run-1",
        path_id="scenario-capex-shock",
        source_intervention_id="capex-slowdown",
        target_variable_id="hyperscaler.ai_capex_growth",
        mechanism_model_id="scenario-intervention",
        gross_effect=-0.2,
        overlap_adjustment=0.0,
        net_effect=-0.2,
        units="ratio",
        time_step=0,
    )


def test_network_propagation_applies_declared_lags_and_reconciles_each_target() -> None:
    ledger = propagate_effect(_root_effect(), _plan())

    assert [
        (item.target_variable_id, item.time_step, item.net_effect) for item in ledger.contributions
    ] == [
        ("hyperscaler.ai_capex_growth", 0, -0.2),
        ("accelerator.demand_growth", 1, -0.1),
        ("supplier.revenue_growth", 3, -0.2),
    ]
    assert all(item.unexplained_residual == 0.0 for item in ledger.target_reconciliations)
    assert ledger.content_hash


def test_network_propagation_rejects_a_cycle_without_an_explicit_feedback_solver() -> None:
    with pytest.raises(ValueError, match="feedback solver"):
        _plan(
            edges=(
                _edge(),
                _edge(
                    edge_id="demand-to-capex",
                    source_variable_id="accelerator.demand_growth",
                    target_variable_id="hyperscaler.ai_capex_growth",
                    multiplier=1.0,
                    mechanism_model_id="demand-to-capex-v1",
                    path_id="demand-to-capex",
                    assumption_ids=("reflexivity",),
                ),
            )
        )


def test_network_propagation_plan_cannot_gain_non_candidate_authority() -> None:
    with pytest.raises(ValueError, match="candidate_only"):
        _plan(authority="approved")


def _feedback_variable(variable_id: str, value: float) -> FeedbackVariable:
    return FeedbackVariable(variable_id=variable_id, value=value, unit="ratio").sealed()


def _feedback_rule(**updates: object) -> FeedbackRule:
    values: dict[str, object] = {
        "rule_id": "a-to-b",
        "source_variable_id": "a",
        "target_variable_id": "b",
        "unit": "ratio",
        "multiplier": 0.5,
    }
    values.update(updates)
    return FeedbackRule(**values).sealed()


def test_feedback_solver_converges_deterministically_with_declared_tolerance() -> None:
    policy = FeedbackConvergencePolicy(
        policy_id="fixed-point-v1", tolerance=0.000001, max_iterations=100, damping=1.0
    ).sealed()

    result = solve_feedback(
        (_feedback_variable("a", 1.0), _feedback_variable("b", 0.0)),
        (
            _feedback_rule(),
            _feedback_rule(rule_id="b-to-a", source_variable_id="b", target_variable_id="a"),
        ),
        policy,
    )

    assert result.iterations > 1
    assert {value.variable_id: value.value for value in result.values} == pytest.approx(
        {"a": 4 / 3, "b": 2 / 3}
    )
    assert result.content_hash


def test_feedback_solver_fails_when_the_declared_budget_does_not_converge() -> None:
    policy = FeedbackConvergencePolicy(
        policy_id="fixed-point-v1", tolerance=0.000001, max_iterations=3, damping=1.0
    ).sealed()

    with pytest.raises(ValueError, match="did not converge"):
        solve_feedback(
            (_feedback_variable("a", 1.0),),
            (_feedback_rule(target_variable_id="a", multiplier=2.0),),
            policy,
        )


def test_feedback_result_rejects_an_unbound_policy_hash() -> None:
    policy = FeedbackConvergencePolicy(
        policy_id="fixed-point-v1", tolerance=0.000001, max_iterations=100, damping=1.0
    ).sealed()
    result = solve_feedback(
        (_feedback_variable("a", 1.0),),
        (_feedback_rule(target_variable_id="a", multiplier=0.5),),
        policy,
    )

    with pytest.raises(ValueError, match="policy hash"):
        FeedbackSolveResult(
            policy_hash="a" * 64,
            policy=policy,
            values=result.values,
            iterations=result.iterations,
        ).sealed()


def test_network_propagation_rejects_an_unregistered_mechanism() -> None:
    unregistered_edge = _edge(mechanism_model_id="no-such-mechanism")
    with pytest.raises(ValueError, match="not registered"):
        _plan(edges=(unregistered_edge,), mechanism_registry=_registry((_edge(),)))


def test_network_propagation_rejects_multiple_effects_on_the_same_target_step() -> None:
    plan = _plan(
        edges=(
            _edge(),
            _edge(
                edge_id="alternative-capex-to-demand",
                mechanism_model_id="alternative-capex-to-demand-v1",
                path_id="alternative-capex-to-demand",
                multiplier=0.25,
                assumption_ids=("alternative-exposure",),
            ),
        )
    )

    with pytest.raises(ValueError, match="double count"):
        propagate_effect(_root_effect(), plan)


def test_network_propagation_requires_registered_mechanisms_from_its_snapshot_graph() -> None:
    edge = _edge()
    with pytest.raises(ValueError, match="causal graph"):
        _plan(edges=(edge,), mechanism_registry=_registry((edge,), causal_graph_hash="c" * 64))
