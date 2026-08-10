from datetime import UTC, datetime, timedelta

import pytest

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
from aegis.world_model.contributions import (
    EffectContribution,
    EffectContributionLedger,
    TargetEffectReconciliation,
)
from aegis.world_model.runs import (
    HistoricalReplayEvaluation,
    HistoricalReplayFixture,
    ScenarioRunManifest,
    ScenarioRunResult,
    run_historical_fixture,
)
from aegis.world_model.scenario import CompiledScenario, compile_scenario
from aegis.world_model.twin import TwinTransition

NOW = datetime(2024, 1, 1, tzinfo=UTC)


def _manifest(**updates: object) -> ScenarioRunManifest:
    values: dict[str, object] = {
        "scenario_run_id": "ai-infrastructure-run-1",
        "world_snapshot_hash": "a" * 64,
        "compiled_scenario_hash": "b" * 64,
        "mechanism_registry_hash": "c" * 64,
        "domain_pack_id": "ai-infrastructure",
        "domain_pack_version": "1.0.0",
        "twin_id": "capex-to-supplier-revenue-twin",
        "random_seed": 7,
        "code_revision": "test-revision",
        "created_at": NOW,
    }
    values.update(updates)
    return ScenarioRunManifest(**values)


def test_scenario_run_manifest_is_deterministically_sealed_and_candidate_only() -> None:
    manifest = _manifest().sealed()

    assert manifest.content_hash
    assert manifest.sealed().content_hash == manifest.content_hash
    with pytest.raises(ValueError, match="candidate_only"):
        manifest.model_copy(update={"authority": "approved"})


def _variable(variable_id: str, value: float, unit: str) -> WorldVariable:
    return WorldVariable(
        variable_id=variable_id,
        value=value,
        unit=unit,
        provenance=VariableProvenance.OBSERVED,
        available_at=NOW,
        evidence_ids=("fixture-evidence",),
        uncertainty_label="engineering-fixture",
    )


def _snapshot() -> WorldSnapshot:
    return WorldSnapshot(
        snapshot_id="ai-infrastructure-fixture",
        as_of=NOW,
        pit_snapshot_hash="a" * 64,
        causal_graph_hash="b" * 64,
        variables=(
            _variable("hyperscaler.ai_capex_growth", 0.2, "ratio"),
            _variable("supplier.revenue", 10.0, "usd_millions"),
            _variable("supplier.cash_from_revenue", 8.0, "usd_millions"),
            _variable("supplier.revenue_capacity", 20.0, "usd_millions"),
        ),
        random_seed=7,
        code_revision="test-revision",
    ).sealed()


def _compiled(snapshot: WorldSnapshot) -> CompiledScenario:
    return compile_scenario(
        snapshot,
        (
            ScenarioIntervention(
                intervention_id="capex-increase",
                target_variable_id="hyperscaler.ai_capex_growth",
                absolute_change=0.1,
                starts_at=NOW,
                rationale="engineering-only candidate fixture",
                assumption_ids=("capex-pass-through",),
            ),
        ),
    )


def _registry(*, causal_graph_hash: str = "b" * 64, **updates: object) -> MechanismRegistry:
    mechanism = VersionedMechanism(
        mechanism=MechanismDefinition(
            mechanism_id="capex-to-supplier-revenue",
            causal_edge_id="capex-to-supplier-revenue-edge",
            domain_pack="ai-infrastructure",
            input_variable_ids=("hyperscaler.ai_capex_growth",),
            output_variable_ids=("supplier.revenue", "supplier.cash_from_revenue"),
            assumption_ids=("capex-pass-through",),
        ),
        version="1.0.0",
        domain_pack_id="ai-infrastructure",
        domain_pack_version="1.0.0",
        causal_graph_hash=causal_graph_hash,
        domain_manifest_hash=AI_INFRASTRUCTURE_DOMAIN.content_hash,
    ).sealed()
    values: dict[str, object] = {
        "registry_id": "ai-infrastructure-mechanisms",
        "version": "1.0.0",
        "domain_pack_id": "ai-infrastructure",
        "domain_pack_version": "1.0.0",
        "domain_manifest_hash": AI_INFRASTRUCTURE_DOMAIN.content_hash,
        "mechanisms": (mechanism,),
    }
    values.update(updates)
    return MechanismRegistry(**values).sealed()


def _twin(registry: MechanismRegistry) -> CapexToSupplierRevenueTwin:
    return CapexToSupplierRevenueTwin(
        CapexToSupplierRevenueParameters(
            parameter_draw_id="draw-7",
            capex_growth_to_revenue_elasticity=0.2,
            cash_conversion_ratio=0.8,
        ),
        registry,
    )


def _transition_bound_to_registry(
    transition: TwinTransition, registry: MechanismRegistry
) -> TwinTransition:
    payload = transition.model_dump(mode="json", exclude={"content_hash"})
    payload["mechanism_registry_hash"] = registry.content_hash
    return TwinTransition.model_validate(payload).sealed()


def _ledger(run_id: str) -> EffectContributionLedger:
    contribution = EffectContribution(
        contribution_id="capex-effect",
        simulation_id=run_id,
        path_id="capex-stress",
        source_intervention_id="capex-increase",
        target_variable_id="hyperscaler.ai_capex_growth",
        mechanism_model_id="capex-to-supplier-revenue",
        gross_effect=0.1,
        overlap_adjustment=0.0,
        net_effect=0.1,
        units="ratio",
        time_step=0,
    )
    return EffectContributionLedger(
        simulation_id=run_id,
        contributions=(contribution,),
        target_reconciliations=(
            TargetEffectReconciliation(
                target_variable_id="hyperscaler.ai_capex_growth",
                units="ratio",
                time_step=0,
                declared_simulated_total=0.1,
                unexplained_residual=0.0,
            ),
        ),
    ).sealed()


def test_historical_fixture_runner_is_no_io_and_reports_engineering_only_error_bounds() -> None:
    snapshot = _snapshot()
    compiled = _compiled(snapshot)
    registry = _registry()
    manifest = _manifest(
        world_snapshot_hash=snapshot.content_hash,
        compiled_scenario_hash=compiled.content_hash,
        mechanism_registry_hash=registry.content_hash,
    ).sealed()
    fixture = HistoricalReplayFixture(
        fixture_id="ai-capex-engineering-fixture",
        as_of=NOW,
        world_snapshot_hash=snapshot.content_hash,
        compiled_scenario_hash=compiled.content_hash,
        target_variable_id="supplier.revenue",
        expected_value=10.2,
        unit="usd_millions",
        error_bound=0.01,
    ).sealed()

    evaluation = run_historical_fixture(
        fixture, manifest, _twin(registry), snapshot, compiled, _ledger(manifest.scenario_run_id)
    )
    repeated = run_historical_fixture(
        fixture, manifest, _twin(registry), snapshot, compiled, _ledger(manifest.scenario_run_id)
    )

    assert evaluation.absolute_error == pytest.approx(0.0)
    assert evaluation.within_error_bound
    assert evaluation.release_disposition == "release_gated"
    assert evaluation.model_dump_json() == repeated.model_dump_json()


def test_scenario_run_result_rejects_forged_lineage_or_unsupported_full_status() -> None:
    snapshot = _snapshot()
    compiled = _compiled(snapshot)
    registry = _registry()
    transition = _twin(registry).transition_compiled(snapshot, compiled)

    with pytest.raises(ValueError, match="compiled scenario"):
        ScenarioRunResult(
            manifest=_manifest(
                world_snapshot_hash=snapshot.content_hash,
                compiled_scenario_hash="d" * 64,
                mechanism_registry_hash=registry.content_hash,
            ).sealed(),
            compiled_scenario=compiled,
            mechanism_registry=registry,
            transition=transition,
            contribution_ledger=_ledger("ai-infrastructure-run-1"),
        ).sealed()
    empty_registry = _registry(mechanisms=())
    with pytest.raises(ValueError, match="registered support"):
        ScenarioRunResult(
            manifest=_manifest(
                world_snapshot_hash=snapshot.content_hash,
                compiled_scenario_hash=compiled.content_hash,
                mechanism_registry_hash=empty_registry.content_hash,
            ).sealed(),
            compiled_scenario=compiled,
            mechanism_registry=empty_registry,
            transition=_transition_bound_to_registry(transition, empty_registry),
            contribution_ledger=_ledger("ai-infrastructure-run-1"),
            support_status="fully_supported",
        ).sealed()


def test_historical_fixture_runner_rejects_a_foreign_domain_manifest() -> None:
    snapshot = _snapshot()
    compiled = _compiled(snapshot)
    registry = _registry()
    manifest = _manifest(
        world_snapshot_hash=snapshot.content_hash,
        compiled_scenario_hash=compiled.content_hash,
        mechanism_registry_hash=registry.content_hash,
        domain_pack_id="foreign-domain",
        domain_pack_version="9.9.9",
    ).sealed()
    fixture = HistoricalReplayFixture(
        fixture_id="ai-capex-engineering-fixture",
        as_of=NOW,
        world_snapshot_hash=snapshot.content_hash,
        compiled_scenario_hash=compiled.content_hash,
        target_variable_id="supplier.revenue",
        expected_value=10.2,
        unit="usd_millions",
        error_bound=0.01,
    ).sealed()

    with pytest.raises(ValueError, match="domain"):
        run_historical_fixture(
            fixture,
            manifest,
            _twin(registry),
            snapshot,
            compiled,
            _ledger(manifest.scenario_run_id),
        )


@pytest.mark.parametrize(
    ("manifest_update", "message"),
    (
        ({"random_seed": 999}, "random seed"),
        ({"code_revision": "forged-revision"}, "code revision"),
    ),
)
def test_scenario_run_result_binds_manifest_provenance_to_its_snapshot(
    manifest_update: dict[str, object], message: str
) -> None:
    snapshot = _snapshot()
    compiled = _compiled(snapshot)
    registry = _registry()
    manifest = _manifest(
        world_snapshot_hash=snapshot.content_hash,
        compiled_scenario_hash=compiled.content_hash,
        mechanism_registry_hash=registry.content_hash,
        **manifest_update,
    ).sealed()

    with pytest.raises(ValueError, match=message):
        ScenarioRunResult(
            manifest=manifest,
            compiled_scenario=compiled,
            mechanism_registry=registry,
            transition=_twin(registry).transition_compiled(snapshot, compiled),
            contribution_ledger=_ledger(manifest.scenario_run_id),
        ).sealed()


def test_scenario_run_result_requires_registry_graph_to_match_its_snapshot() -> None:
    snapshot = _snapshot()
    compiled = _compiled(snapshot)
    transition_registry = _registry()
    registry = _registry(causal_graph_hash="c" * 64)
    manifest = _manifest(
        world_snapshot_hash=snapshot.content_hash,
        compiled_scenario_hash=compiled.content_hash,
        mechanism_registry_hash=registry.content_hash,
    ).sealed()

    with pytest.raises(ValueError, match="causal graph"):
        ScenarioRunResult(
            manifest=manifest,
            compiled_scenario=compiled,
            mechanism_registry=registry,
            transition=_transition_bound_to_registry(
                _twin(transition_registry).transition_compiled(snapshot, compiled), registry
            ),
            contribution_ledger=_ledger(manifest.scenario_run_id),
            support_status="fully_supported",
        ).sealed()


def test_scenario_run_result_rejects_unregistered_support_even_when_stress_only() -> None:
    snapshot = _snapshot()
    compiled = _compiled(snapshot)
    transition_registry = _registry()
    registry = _registry(mechanisms=())
    manifest = _manifest(
        world_snapshot_hash=snapshot.content_hash,
        compiled_scenario_hash=compiled.content_hash,
        mechanism_registry_hash=registry.content_hash,
    ).sealed()

    with pytest.raises(ValueError, match="registered support"):
        ScenarioRunResult(
            manifest=manifest,
            compiled_scenario=compiled,
            mechanism_registry=registry,
            transition=_transition_bound_to_registry(
                _twin(transition_registry).transition_compiled(snapshot, compiled), registry
            ),
            contribution_ledger=_ledger(manifest.scenario_run_id),
            support_status="stress_only",
        ).sealed()


def test_scenario_run_result_requires_the_compiled_snapshot_cutoff_used_by_transition() -> None:
    snapshot = _snapshot()
    compiled = _compiled(snapshot)
    earlier_compiled = CompiledScenario(
        world_snapshot_hash=compiled.world_snapshot_hash,
        snapshot_as_of=NOW - timedelta(days=1),
        interventions=compiled.interventions,
        affected_variable_ids=compiled.affected_variable_ids,
    ).sealed()
    registry = _registry()
    manifest = _manifest(
        world_snapshot_hash=snapshot.content_hash,
        compiled_scenario_hash=earlier_compiled.content_hash,
        mechanism_registry_hash=registry.content_hash,
    ).sealed()

    with pytest.raises(ValueError, match="cutoff"):
        ScenarioRunResult(
            manifest=manifest,
            compiled_scenario=earlier_compiled,
            mechanism_registry=registry,
            transition=_twin(registry).transition_compiled(snapshot, compiled),
            contribution_ledger=_ledger(manifest.scenario_run_id),
        ).sealed()


def test_scenario_run_result_requires_the_registry_used_by_its_transition() -> None:
    snapshot = _snapshot()
    compiled = _compiled(snapshot)
    transition_registry = _registry()
    registry = _registry(registry_id="different-ai-infrastructure-mechanisms")
    manifest = _manifest(
        world_snapshot_hash=snapshot.content_hash,
        compiled_scenario_hash=compiled.content_hash,
        mechanism_registry_hash=registry.content_hash,
    ).sealed()

    with pytest.raises(ValueError, match="mechanism registry"):
        ScenarioRunResult(
            manifest=manifest,
            compiled_scenario=compiled,
            mechanism_registry=registry,
            transition=_twin(transition_registry).transition_compiled(snapshot, compiled),
            contribution_ledger=_ledger(manifest.scenario_run_id),
        ).sealed()


def test_historical_replay_evaluation_rejects_an_actual_value_not_in_its_transition() -> None:
    snapshot = _snapshot()
    compiled = _compiled(snapshot)
    registry = _registry()
    manifest = _manifest(
        world_snapshot_hash=snapshot.content_hash,
        compiled_scenario_hash=compiled.content_hash,
        mechanism_registry_hash=registry.content_hash,
    ).sealed()
    fixture = HistoricalReplayFixture(
        fixture_id="fabricated-replay-fixture",
        as_of=NOW,
        world_snapshot_hash=snapshot.content_hash,
        compiled_scenario_hash=compiled.content_hash,
        target_variable_id="supplier.revenue",
        expected_value=999.0,
        unit="usd_millions",
        error_bound=0.0,
    ).sealed()
    run = run_historical_fixture(
        fixture, manifest, _twin(registry), snapshot, compiled, _ledger(manifest.scenario_run_id)
    )

    with pytest.raises(ValueError, match="transition"):
        HistoricalReplayEvaluation(
            fixture=fixture,
            scenario_run=run.scenario_run,
            actual_value=999.0,
            absolute_error=0.0,
            within_error_bound=True,
        ).sealed()
