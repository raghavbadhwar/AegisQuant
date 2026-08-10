from datetime import timedelta
from pathlib import Path

import pytest

from aegis.fundamentals import load_fundamental_fixture
from aegis.fundamentals.service import _compute_preliminary_research
from aegis.world_model.contracts import VariableProvenance, WorldSnapshot, WorldVariable
from aegis.world_model.fcff_adapter import (
    TwinOperatingDriver,
    TwinOperatingOutput,
    adapt_twin_output_to_fcff_forecast,
)
from aegis.world_model.twin import TwinState, TwinTransition


def _statements():  # type: ignore[no-untyped-def]
    fixture = Path(__file__).parents[2] / "data/fixtures/fundamentals/cmpd.json"
    request, snapshot, inputs = load_fundamental_fixture(fixture)
    result = _compute_preliminary_research(request, snapshot, inputs)
    assert result.statements is not None
    return result.statements


def _driver(year: int, **updates: object) -> TwinOperatingDriver:
    values: dict[str, object] = {
        "year": year,
        "revenue_growth": 0.1,
        "operating_margin": 0.2,
        "tax_rate": 0.2,
        "reinvestment_rate": 0.3,
        "share_dilution": 0.01,
        "assumption_ids": ("candidate-twin-driver",),
    }
    values.update(updates)
    return TwinOperatingDriver(**values).sealed()


def _transition(as_of: object) -> TwinTransition:
    source_as_of = as_of - timedelta(days=30)
    variable = WorldVariable(
        variable_id="supplier.revenue",
        value=10.0,
        unit="usd_millions",
        provenance=VariableProvenance.OBSERVED,
        available_at=source_as_of,
        evidence_ids=("fixture-evidence",),
        uncertainty_label="engineering-fixture",
    )
    snapshot = WorldSnapshot(
        snapshot_id="fcff-adapter-fixture",
        as_of=source_as_of,
        pit_snapshot_hash="a" * 64,
        causal_graph_hash="b" * 64,
        variables=(variable,),
        random_seed=7,
        code_revision="test-revision",
    ).sealed()
    source = TwinState(
        state_id="fcff-candidate-twin-source",
        twin_id="fcff-candidate-twin",
        domain_pack_id="ai-infrastructure",
        domain_pack_version="1.0.0",
        world_snapshot_hash=snapshot.content_hash,
        world_snapshot=snapshot,
        as_of=source_as_of,
        variables=(variable,),
    ).sealed()
    target = TwinState(
        state_id="fcff-candidate-twin-target",
        twin_id="fcff-candidate-twin",
        domain_pack_id="ai-infrastructure",
        domain_pack_version="1.0.0",
        world_snapshot_hash=snapshot.content_hash,
        world_snapshot=snapshot,
        as_of=as_of,
        variables=(variable,),
    ).sealed()
    return TwinTransition(
        transition_id="fcff-candidate-transition",
        twin_id="fcff-candidate-twin",
        domain_pack_id="ai-infrastructure",
        domain_pack_version="1.0.0",
        from_state_id=source.state_id,
        from_state=source,
        to_state=target,
        parameter_draw_id="fcff-candidate-draw",
        time_step=timedelta(days=30),
        support_ids=("candidate-mechanism@1.0.0",),
    ).sealed()


def _output(**updates: object) -> TwinOperatingOutput:
    statements = _statements()
    years = [period.fiscal_year for period in statements.adjusted_periods[-2:]]
    transition = _transition(statements.as_of)
    values: dict[str, object] = {
        "output_id": "supplier-operating-output-v1",
        "ticker": statements.ticker,
        "as_of": statements.as_of,
        "scenario": "base",
        "source_transition_hash": transition.content_hash,
        "world_snapshot_hash": transition.from_state.world_snapshot_hash,
        "source_transition": transition,
        "drivers": (_driver(years[-1] + 1), _driver(years[-1] + 2)),
        "terminal_growth": 0.025,
        "terminal_roic": 0.15,
    }
    values.update(updates)
    return TwinOperatingOutput(**values)


def test_candidate_twin_output_adapts_to_the_existing_fcff_forecast_interface() -> None:
    statements = _statements()
    output = _output().sealed()

    forecast, lineages = adapt_twin_output_to_fcff_forecast(
        output, statements, evidence_ids=("fixture-evidence",)
    )

    assert forecast.scenario == "base"
    assert len(forecast.periods) == 2
    assert forecast.periods[-1].fcff
    assert lineages


def test_candidate_twin_output_cannot_gain_valuation_or_release_authority() -> None:
    with pytest.raises(ValueError, match="candidate_only"):
        _output(authority="approved")


def test_twin_operating_output_rejects_unbound_transition_hashes() -> None:
    with pytest.raises(ValueError, match="source transition"):
        _output(source_transition_hash="a" * 64, world_snapshot_hash="b" * 64).sealed()
