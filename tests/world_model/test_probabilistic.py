import pytest

from aegis.world_model.probabilistic import (
    BoundedOutcomeModel,
    ComputedUncertaintyDecomposition,
    FinancialValuationOutcome,
    FrozenParameterArtifact,
    MonteCarloRunManifest,
    MonteCarloRunResult,
    OneAtATimeSensitivity,
    OutcomeParameterTerm,
    ParameterDraw,
    ScenarioGridPoint,
    ScenarioGridResult,
    ScenarioLabel,
    UncertaintyComponentSamples,
    compute_uncertainty_decomposition,
    evaluate_scenario_grid,
    one_at_a_time_sensitivity,
    run_bounded_monte_carlo,
)


def _parameter() -> FrozenParameterArtifact:
    return FrozenParameterArtifact(
        artifact_id="capex-elasticity-posterior-v1",
        parameter_id="capex-to-revenue-elasticity",
        version="1.0.0",
        distribution="normal",
        lower_bound=0.0,
        upper_bound=1.0,
        mean=0.2,
        standard_deviation=0.05,
        evidence_ids=("engineering-fixture",),
    ).sealed()


def test_monte_carlo_run_is_byte_identical_for_the_same_seed_and_frozen_draws() -> None:
    parameter = _parameter()
    manifest = MonteCarloRunManifest(
        run_id="ai-infrastructure-mc-v1",
        random_seed=7,
        sample_count=4,
        parameter_artifacts=(parameter,),
        scenario=ScenarioLabel.BASE,
        code_revision="test-revision",
    ).sealed()
    model = BoundedOutcomeModel(
        model_id="supplier-operating-stress-v1",
        financial_intercept=10.0,
        valuation_intercept=12.0,
        terms=(
            OutcomeParameterTerm(
                parameter_id=parameter.parameter_id,
                financial_coefficient=2.0,
                valuation_coefficient=3.0,
            ).sealed(),
        ),
        financial_bounds=(0.0, 20.0),
        valuation_bounds=(0.0, 25.0),
    ).sealed()

    first = run_bounded_monte_carlo(manifest, model)
    repeated = run_bounded_monte_carlo(manifest, model)

    assert first.model_dump_json() == repeated.model_dump_json()
    assert len(first.outcomes) == 4
    assert {outcome.scenario for outcome in first.outcomes} == {ScenarioLabel.BASE}


def test_monte_carlo_result_rejects_an_outcome_that_does_not_reconcile_to_its_draws() -> None:
    parameter = _parameter()
    manifest = MonteCarloRunManifest(
        run_id="ai-infrastructure-mc-v1",
        random_seed=7,
        sample_count=1,
        parameter_artifacts=(parameter,),
        code_revision="test-revision",
    ).sealed()
    model = BoundedOutcomeModel(
        model_id="supplier-operating-stress-v1",
        financial_intercept=10.0,
        valuation_intercept=12.0,
        terms=(
            OutcomeParameterTerm(
                parameter_id=parameter.parameter_id,
                financial_coefficient=2.0,
                valuation_coefficient=3.0,
            ).sealed(),
        ),
        financial_bounds=(0.0, 20.0),
        valuation_bounds=(0.0, 25.0),
    ).sealed()
    run = run_bounded_monte_carlo(manifest, model)
    payload = run.outcomes[0].model_dump(mode="json", exclude={"content_hash"})
    payload["financial_value"] = 11.0
    forged = FinancialValuationOutcome.model_validate(payload).sealed()

    with pytest.raises(ValueError, match="reconcile"):
        MonteCarloRunResult(manifest=manifest, model=model, outcomes=(forged,)).sealed()


def test_monte_carlo_result_rejects_draws_that_do_not_replay_the_manifest_seed() -> None:
    parameter = _parameter()
    manifest = MonteCarloRunManifest(
        run_id="ai-infrastructure-mc-v1",
        random_seed=7,
        sample_count=1,
        parameter_artifacts=(parameter,),
        code_revision="test-revision",
    ).sealed()
    model = BoundedOutcomeModel(
        model_id="supplier-operating-stress-v1",
        financial_intercept=10.0,
        valuation_intercept=12.0,
        terms=(
            OutcomeParameterTerm(
                parameter_id=parameter.parameter_id,
                financial_coefficient=2.0,
                valuation_coefficient=3.0,
            ).sealed(),
        ),
        financial_bounds=(0.0, 20.0),
        valuation_bounds=(0.0, 25.0),
    ).sealed()
    run = run_bounded_monte_carlo(manifest, model)
    draw_payload = (
        run.outcomes[0].parameter_draws[0].model_dump(mode="json", exclude={"content_hash"})
    )
    draw_payload["value"] = 0.2
    forged_draw = ParameterDraw.model_validate(draw_payload).sealed()
    outcome_payload = run.outcomes[0].model_dump(mode="json", exclude={"content_hash"})
    outcome_payload["parameter_draws"] = (forged_draw,)
    outcome_payload["financial_value"] = 10.4
    outcome_payload["valuation_value"] = 12.6
    forged_outcome = FinancialValuationOutcome.model_validate(outcome_payload).sealed()

    with pytest.raises(ValueError, match="seed"):
        MonteCarloRunResult(manifest=manifest, model=model, outcomes=(forged_outcome,)).sealed()


def test_monte_carlo_result_rejects_large_scale_seeded_draw_tampering() -> None:
    parameter = FrozenParameterArtifact(
        artifact_id="large-scale-posterior-v1",
        parameter_id="large-scale-parameter",
        version="1.0.0",
        distribution="normal",
        lower_bound=0.0,
        upper_bound=2_000_000_000_000.0,
        mean=1_000_000_000_000.0,
        standard_deviation=0.1,
        evidence_ids=("engineering-fixture",),
    ).sealed()
    manifest = MonteCarloRunManifest(
        run_id="large-scale-mc-v1",
        random_seed=7,
        sample_count=1,
        parameter_artifacts=(parameter,),
        code_revision="test-revision",
    ).sealed()
    model = BoundedOutcomeModel(
        model_id="large-scale-model-v1",
        financial_intercept=0.0,
        valuation_intercept=0.0,
        terms=(
            OutcomeParameterTerm(
                parameter_id=parameter.parameter_id,
                financial_coefficient=1.0,
                valuation_coefficient=1.0,
            ).sealed(),
        ),
        financial_bounds=(0.0, 3_000_000_000_000.0),
        valuation_bounds=(0.0, 3_000_000_000_000.0),
    ).sealed()
    run = run_bounded_monte_carlo(manifest, model)
    draw_payload = (
        run.outcomes[0].parameter_draws[0].model_dump(mode="json", exclude={"content_hash"})
    )
    draw_payload["value"] += 1.0
    forged_draw = ParameterDraw.model_validate(draw_payload).sealed()
    outcome_payload = run.outcomes[0].model_dump(mode="json", exclude={"content_hash"})
    outcome_payload["parameter_draws"] = (forged_draw,)
    forged_outcome = FinancialValuationOutcome.model_validate(outcome_payload).sealed()

    with pytest.raises(ValueError, match="seed"):
        MonteCarloRunResult(manifest=manifest, model=model, outcomes=(forged_outcome,)).sealed()


def test_monte_carlo_result_rejects_an_outcome_scenario_outside_its_manifest() -> None:
    parameter = _parameter()
    manifest = MonteCarloRunManifest(
        run_id="ai-infrastructure-mc-v1",
        random_seed=7,
        sample_count=1,
        parameter_artifacts=(parameter,),
        scenario=ScenarioLabel.BASE,
        code_revision="test-revision",
    ).sealed()
    model = BoundedOutcomeModel(
        model_id="supplier-operating-stress-v1",
        financial_intercept=10.0,
        valuation_intercept=12.0,
        terms=(
            OutcomeParameterTerm(
                parameter_id=parameter.parameter_id,
                financial_coefficient=2.0,
                valuation_coefficient=3.0,
            ).sealed(),
        ),
        financial_bounds=(0.0, 20.0),
        valuation_bounds=(0.0, 25.0),
    ).sealed()
    run = run_bounded_monte_carlo(manifest, model)
    outcome_payload = run.outcomes[0].model_dump(mode="json", exclude={"content_hash"})
    outcome_payload["scenario"] = ScenarioLabel.BEAR
    forged_outcome = FinancialValuationOutcome.model_validate(outcome_payload).sealed()

    with pytest.raises(ValueError, match="scenario"):
        MonteCarloRunResult(manifest=manifest, model=model, outcomes=(forged_outcome,)).sealed()


def test_monte_carlo_result_rejects_non_contiguous_draw_indexes() -> None:
    parameter = _parameter()
    manifest = MonteCarloRunManifest(
        run_id="ai-infrastructure-mc-v1",
        random_seed=7,
        sample_count=1,
        parameter_artifacts=(parameter,),
        code_revision="test-revision",
    ).sealed()
    model = BoundedOutcomeModel(
        model_id="supplier-operating-stress-v1",
        financial_intercept=10.0,
        valuation_intercept=12.0,
        terms=(
            OutcomeParameterTerm(
                parameter_id=parameter.parameter_id,
                financial_coefficient=2.0,
                valuation_coefficient=3.0,
            ).sealed(),
        ),
        financial_bounds=(0.0, 20.0),
        valuation_bounds=(0.0, 25.0),
    ).sealed()
    run = run_bounded_monte_carlo(manifest, model)
    draw = (
        run.outcomes[0]
        .parameter_draws[0]
        .model_copy(update={"draw_index": 99, "content_hash": None})
        .sealed()
    )
    outcome = (
        run.outcomes[0]
        .model_copy(update={"draw_index": 99, "parameter_draws": (draw,), "content_hash": None})
        .sealed()
    )

    with pytest.raises(ValueError, match="draw indexes"):
        MonteCarloRunResult(manifest=manifest, model=model, outcomes=(outcome,)).sealed()


def test_uncertainty_decomposition_is_computed_from_sealed_component_samples() -> None:
    parameter = UncertaintyComponentSamples(
        component="parameter",
        samples=(1.0, 3.0),
    ).sealed()
    state = UncertaintyComponentSamples(component="state", samples=(2.0, 2.0)).sealed()

    result = compute_uncertainty_decomposition((parameter, state))

    assert result.total_variance == 1.0
    assert result.parameter_share == 1.0
    assert result.state_share == 0.0
    assert result.content_hash


def test_uncertainty_decomposition_rejects_forged_computed_values() -> None:
    parameter = UncertaintyComponentSamples(
        component="parameter",
        samples=(1.0, 3.0),
    ).sealed()
    result = compute_uncertainty_decomposition((parameter,))
    payload = result.model_dump(mode="json", exclude={"content_hash"})
    payload["total_variance"] = 99.0

    with pytest.raises(ValueError, match="computed"):
        ComputedUncertaintyDecomposition.model_validate(payload).sealed()


def test_one_at_a_time_sensitivity_uses_frozen_parameter_bounds() -> None:
    parameter = _parameter()
    model = BoundedOutcomeModel(
        model_id="supplier-operating-stress-v1",
        financial_intercept=10.0,
        valuation_intercept=12.0,
        terms=(
            OutcomeParameterTerm(
                parameter_id=parameter.parameter_id,
                financial_coefficient=2.0,
                valuation_coefficient=3.0,
            ).sealed(),
        ),
        financial_bounds=(0.0, 20.0),
        valuation_bounds=(0.0, 25.0),
    ).sealed()

    result = one_at_a_time_sensitivity(model, (parameter,), parameter.parameter_id)

    assert result.low_financial_value == 10.0
    assert result.high_financial_value == 12.0
    assert result.content_hash


def test_one_at_a_time_sensitivity_rejects_forged_derived_values() -> None:
    parameter = _parameter()
    model = BoundedOutcomeModel(
        model_id="supplier-operating-stress-v1",
        financial_intercept=10.0,
        valuation_intercept=12.0,
        terms=(
            OutcomeParameterTerm(
                parameter_id=parameter.parameter_id,
                financial_coefficient=2.0,
                valuation_coefficient=3.0,
            ).sealed(),
        ),
        financial_bounds=(0.0, 20.0),
        valuation_bounds=(0.0, 25.0),
    ).sealed()
    result = one_at_a_time_sensitivity(model, (parameter,), parameter.parameter_id)
    payload = result.model_dump(mode="json", exclude={"content_hash"})
    payload["high_financial_value"] = 99.0

    with pytest.raises(ValueError, match="reconcile"):
        OneAtATimeSensitivity.model_validate(payload).sealed()


def test_scenario_grid_returns_sealed_bear_base_bull_candidate_outcomes() -> None:
    parameter = _parameter()
    model = BoundedOutcomeModel(
        model_id="supplier-operating-stress-v1",
        financial_intercept=10.0,
        valuation_intercept=12.0,
        terms=(
            OutcomeParameterTerm(
                parameter_id=parameter.parameter_id,
                financial_coefficient=2.0,
                valuation_coefficient=3.0,
            ).sealed(),
        ),
        financial_bounds=(0.0, 20.0),
        valuation_bounds=(0.0, 25.0),
    ).sealed()
    points = (
        ScenarioGridPoint(
            scenario_id="bear-case",
            scenario=ScenarioLabel.BEAR,
            parameter_values=((parameter.parameter_id, 0.0),),
        ).sealed(),
        ScenarioGridPoint(
            scenario_id="base-case",
            scenario=ScenarioLabel.BASE,
            parameter_values=((parameter.parameter_id, 0.2),),
        ).sealed(),
        ScenarioGridPoint(
            scenario_id="bull-case",
            scenario=ScenarioLabel.BULL,
            parameter_values=((parameter.parameter_id, 1.0),),
        ).sealed(),
    )

    result = evaluate_scenario_grid(model, (parameter,), points)

    assert [outcome.scenario for outcome in result.outcomes] == [
        ScenarioLabel.BEAR,
        ScenarioLabel.BASE,
        ScenarioLabel.BULL,
    ]
    assert result.outcomes[0].financial_value == 10.0
    assert result.outcomes[-1].valuation_value == 15.0


def test_scenario_grid_result_rejects_forged_derived_outcomes() -> None:
    parameter = _parameter()
    model = BoundedOutcomeModel(
        model_id="supplier-operating-stress-v1",
        financial_intercept=10.0,
        valuation_intercept=12.0,
        terms=(
            OutcomeParameterTerm(
                parameter_id=parameter.parameter_id,
                financial_coefficient=2.0,
                valuation_coefficient=3.0,
            ).sealed(),
        ),
        financial_bounds=(0.0, 20.0),
        valuation_bounds=(0.0, 25.0),
    ).sealed()
    point = ScenarioGridPoint(
        scenario_id="base-case",
        scenario=ScenarioLabel.BASE,
        parameter_values=((parameter.parameter_id, 0.2),),
    ).sealed()
    result = evaluate_scenario_grid(model, (parameter,), (point,))
    forged_outcome = (
        result.outcomes[0]
        .model_copy(update={"financial_value": 99.0, "content_hash": None})
        .sealed()
    )
    payload = result.model_dump(mode="json", exclude={"content_hash"})
    payload["outcomes"] = (forged_outcome,)

    with pytest.raises(ValueError, match="reconcile"):
        ScenarioGridResult.model_validate(payload).sealed()
