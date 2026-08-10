import pytest

from aegis.world_model import contributions


def contribution(**updates: object) -> contributions.EffectContribution:
    values: dict[str, object] = {
        "contribution_id": "contribution-1",
        "simulation_id": "simulation-1",
        "path_id": "capex-to-revenue",
        "source_intervention_id": "capex-slowdown",
        "target_variable_id": "supplier.revenue",
        "mechanism_model_id": "capex-elasticity-v1",
        "gross_effect": -5.0,
        "overlap_adjustment": 1.0,
        "net_effect": -4.0,
        "units": "usd_millions",
        "time_step": 1,
    }
    values.update(updates)
    return contributions.EffectContribution(**values)


def reconciliation(
    declared_simulated_total: float, unexplained_residual: float = 0.0
) -> contributions.TargetEffectReconciliation:
    return contributions.TargetEffectReconciliation(
        target_variable_id="supplier.revenue",
        units="usd_millions",
        time_step=1,
        aggregation_policy="sum",
        declared_simulated_total=declared_simulated_total,
        unexplained_residual=unexplained_residual,
    )


def test_effect_contribution_rejects_unreconciled_net_effect() -> None:
    with pytest.raises(ValueError, match="reconcile"):
        contribution(net_effect=-3.0)


def test_effect_contribution_ledger_rejects_duplicate_contribution_ids() -> None:
    first = contribution()
    duplicate = contribution(path_id="capex-to-margin")

    with pytest.raises(ValueError, match="unique"):
        contributions.EffectContributionLedger(
            simulation_id="simulation-1", contributions=(first, duplicate)
        )


def test_effect_contribution_ledger_rejects_duplicate_economic_paths() -> None:
    first = contribution()
    same_path = contribution(contribution_id="contribution-2")

    with pytest.raises(ValueError, match="economic paths"):
        contributions.EffectContributionLedger(
            simulation_id="simulation-1", contributions=(first, same_path)
        )


def test_effect_contribution_ledger_rejects_forward_parent_references() -> None:
    parent = contribution()
    dependent = contribution(
        contribution_id="contribution-2",
        path_id="revenue-to-margin",
        parent_contribution_ids=("contribution-1",),
    )

    with pytest.raises(ValueError, match="precede"):
        contributions.EffectContributionLedger(
            simulation_id="simulation-1", contributions=(dependent, parent)
        )


def test_effect_contribution_ledger_requires_declared_target_total_reconciliation() -> None:
    with pytest.raises(ValueError, match="target reconciliation"):
        contributions.EffectContributionLedger(
            simulation_id="simulation-1",
            contributions=(contribution(),),
            target_reconciliations=(
                contributions.TargetEffectReconciliation(
                    target_variable_id="supplier.revenue",
                    units="usd_millions",
                    time_step=1,
                    aggregation_policy="sum",
                    declared_simulated_total=-3.0,
                    unexplained_residual=0.0,
                ),
            ),
        )


def test_effect_contribution_ledger_revalidates_model_copy_tampering() -> None:
    with pytest.raises(ValueError, match="net effect must reconcile"):
        contribution().model_copy(update={"net_effect": -3.0})


def test_effect_contribution_ledger_append_preserves_an_immutable_hash_chain() -> None:
    initial = contributions.EffectContributionLedger(
        simulation_id="simulation-1",
        contributions=(contribution(),),
        target_reconciliations=(reconciliation(-4.0),),
    ).sealed()
    follow_on = contribution(
        contribution_id="contribution-2",
        path_id="revenue-to-margin",
        parent_contribution_ids=("contribution-1",),
    )

    extended = initial.append(follow_on, (reconciliation(-8.0),))

    assert extended.parent_ledger_hash == initial.content_hash
    assert extended.contributions == (contribution(), follow_on)
    assert extended.content_hash
