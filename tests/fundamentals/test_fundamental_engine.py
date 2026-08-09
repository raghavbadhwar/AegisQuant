from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from aegis.contracts import (
    CompanyResearchRequest,
    ManagementActionRecord,
    NormalizationAdjustment,
)
from aegis.fundamentals import (
    calculate_dcf,
    load_fundamental_fixture,
    reverse_adjustments,
    solve_implied_growth,
)
from aegis.fundamentals.normalization import raw_snapshot
from aegis.fundamentals.service import _compute_preliminary_research
from aegis.fundamentals.thesis import ThesisLedger, ThesisLedgerError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data/fixtures/fundamentals"
GOLDEN_DOSSIER_HASHES = {
    "acqr": "826c3ad712a8a49d737a567f61e62610099ce229a2c83e0ee1f605713979be9c",
    "bank": "9a7fd69823ce166bd8818fed1028f905e01b2003d294ba3fd91b8099cdf87089",
    "cmpd": "6ebade257ad17bb1b4c390e4881535af86f90826a62b32a0e29435a6d16181d3",
    "cycl": "6adc2bb09444124c68e847310d6aa51dd8945179b32ef6161c914f897f1d16ca",
    "grow": "dcecd2c441d3cdf7802b9c8e804b256cceffe979bab9f3d964a2bfde386422b1",
    "guide": "3ab6de26b7b5ee39ae091cee193221557adb7c2ca207fc3637bf0d86773f2043",
    "warn": "b7b5bfefff8e4164ed50d5d44d2654e95b2153205554ebd846940fcc3be496c4",
}


def dossier(name: str):  # type: ignore[no-untyped-def]
    request, snapshot, inputs = load_fundamental_fixture(FIXTURES / f"{name}.json")
    return _compute_preliminary_research(request, snapshot, inputs)


def test_all_golden_cases_are_deterministic_and_safely_routed() -> None:
    completed = {"cmpd", "grow", "warn", "guide", "acqr"}
    unsupported = {"bank", "cycl"}
    for name in sorted(completed | unsupported):
        first = dossier(name)
        second = dossier(name)
        assert first == second
        assert first.content_hash == GOLDEN_DOSSIER_HASHES[name]
        assert first.abstained is (name in unsupported)
        assert first.alpha_forecast.abstained
        if name in completed:
            assert first.statements is not None
            assert first.metrics is not None
            assert first.thesis is not None
            assert set(first.forecasts) == {"bear", "base", "bull"}
            assert set(first.reverse_dcf) == {
                "revenue_growth",
                "growth_duration",
                "operating_margin",
            }
            assert first.dcf["bear"].value_per_share <= first.dcf["base"].value_per_share
            assert first.dcf["base"].value_per_share <= first.dcf["bull"].value_per_share
            assert first.evidence_ids and first.calculation_ids
            assert first.input_snapshot_hash
            assert first.alpha_forecast.verification_status == "pending"
            assert {
                "fundamental-alpha-v1:calibrated-expected-return",
                "fundamental-alpha-v1:calibrated-probability",
                "fundamental-alpha-v1:calibrated-confidence",
            }.issubset(first.calculation_ids)
            assert first.comparables is not None
            assert {
                "ev_revenue",
                "ev_ebitda",
                "ev_ebit",
                "price_earnings",
            }.issubset(first.comparables.multiple_distributions)
            if name == "cmpd":
                assert "price_fcf" in first.comparables.multiple_distributions


def test_statement_normalisation_preserves_lineage_and_reported_view() -> None:
    result = dossier("cmpd")
    statements = result.statements
    assert statements is not None
    assert reverse_adjustments(statements) == statements.reported_periods
    assert all(period.lineage_by_line_item for period in statements.reported_periods)
    assert all(lineage.input_fact_ids for lineage in statements.calculation_lineage)
    latest = statements.adjusted_periods[-1]
    assert latest.operating_income == pytest.approx(
        latest.revenue - latest.cost_of_revenue - latest.operating_expenses
    )
    assert latest.working_capital == pytest.approx(
        latest.current_assets - latest.current_liabilities
    )
    assert latest.total_assets == pytest.approx(latest.total_liabilities + latest.total_equity)
    assert latest.cash_from_operations == pytest.approx(
        latest.net_income
        + latest.depreciation_amortization
        + latest.stock_based_compensation
        + latest.cash_flow_working_capital_change
        + latest.other_operating_cash_adjustments
    )


def test_metrics_match_independent_hand_calculations_and_warning_case() -> None:
    result = dossier("cmpd")
    statements, metrics = result.statements, result.metrics
    assert statements is not None and metrics is not None
    previous, current = statements.adjusted_periods[-2:]
    assert metrics.revenue_growth == pytest.approx(float(current.revenue / previous.revenue - 1))
    assert metrics.gross_margin == pytest.approx(
        float((current.revenue - current.cost_of_revenue) / current.revenue)
    )
    assert metrics.net_debt == current.total_debt - current.cash
    assert isinstance(metrics.net_debt, Decimal)
    assert isinstance(metrics.fcf_per_share, Decimal)
    warning = dossier("warn")
    assert warning.accounting is not None
    assert warning.accounting.accrual_warning
    assert warning.accounting.sbc_warning
    acquisition = dossier("acqr")
    assert acquisition.accounting is not None and acquisition.accounting.acquisition_warning


def test_dcf_golden_cross_check_and_monotonicity() -> None:
    result = dossier("cmpd")
    forecast = result.forecasts["base"]
    assert isinstance(forecast.periods[0].revenue, Decimal)
    assert isinstance(forecast.periods[0].fcff, Decimal)
    assert isinstance(forecast.periods[0].diluted_shares, Decimal)
    base = result.dcf["base"]
    assert isinstance(base.value_per_share, Decimal)
    assert isinstance(base.enterprise_value, Decimal)
    assert isinstance(result.scenario_valuation.market_price, Decimal)
    rate = Decimal("0.10")
    growth = Decimal("0.025")
    independent_explicit = sum(
        (
            Decimal(str(period.fcff)) / (Decimal("1") + rate) ** index
            for index, period in enumerate(forecast.periods, 1)
        ),
        Decimal("0"),
    )
    independent_terminal = (
        Decimal(str(forecast.periods[-1].nopat))
        * (Decimal("1") + growth)
        * (Decimal("1") - growth / Decimal(str(forecast.terminal_roic)))
        / (rate - growth)
    )
    independent_enterprise = independent_explicit + independent_terminal / (
        Decimal("1") + rate
    ) ** len(forecast.periods)
    assert abs(base.enterprise_value - independent_enterprise) < Decimal("1e-20")
    higher_rate, _ = calculate_dcf(
        forecast,
        discount_rate=0.11,
        terminal_growth=0.025,
        net_debt=base.net_debt,
        evidence_ids=result.evidence_ids,
    )
    higher_growth, _ = calculate_dcf(
        forecast,
        discount_rate=0.10,
        terminal_growth=0.03,
        net_debt=base.net_debt,
        evidence_ids=result.evidence_ids,
    )
    assert higher_rate.value_per_share < base.value_per_share
    assert higher_growth.value_per_share > base.value_per_share


def test_reverse_dcf_round_trip_and_no_root_are_explicit() -> None:
    expected = 0.2
    solved = solve_implied_growth(
        ticker="CMPD",
        market_price=120,
        valuation_for_growth=lambda growth: 100 * (1 + growth),
        lower_bound=-0.5,
        upper_bound=0.5,
        assumption_ids=["round-trip"],
    )
    assert solved.feasible and solved.implied_value == pytest.approx(expected, abs=1e-8)
    impossible = solve_implied_growth(
        ticker="CMPD",
        market_price=1_000,
        valuation_for_growth=lambda growth: 100 * (1 + growth),
        lower_bound=-0.2,
        upper_bound=0.2,
        assumption_ids=["no-root"],
    )
    assert not impossible.feasible and impossible.implied_value is None
    assert impossible.limitations


def test_guidance_deterioration_and_future_actual_exclusion(tmp_path: Path) -> None:
    result = dossier("guide")
    assert result.management is not None
    assert result.management.matured_count == 1
    assert result.management.hit_rate == 0
    fixture = json.loads((FIXTURES / "guide.json").read_text())
    fixture["guidance"][0]["actual_available_at"] = "2026-01-01T00:00:00+00:00"
    path = tmp_path / "future-guidance.json"
    try:
        path.write_text(json.dumps(fixture))
        request, snapshot, inputs = load_fundamental_fixture(path)
        future = _compute_preliminary_research(request, snapshot, inputs)
        assert future.management is not None and future.management.matured_count == 0
    finally:
        path.unlink(missing_ok=True)


def test_management_action_completion_is_causal_and_point_in_time_projected() -> None:
    result = dossier("cmpd")
    assert result.statements is not None
    with pytest.raises(ValidationError, match="completion timestamps"):
        ManagementActionRecord(
            action_id="bad-completion",
            action_type="capital_allocation_promise",
            announced_at=result.request.as_of - timedelta(days=100),
            available_at=result.request.as_of - timedelta(days=99),
            promise="Complete repurchase programme.",
            completed=True,
            evidence_ids=result.evidence_ids,
        )
    with pytest.raises(ValidationError, match="outcome timestamps are not causal"):
        ManagementActionRecord(
            action_id="bad-outcome",
            action_type="acquisition",
            announced_at=result.request.as_of - timedelta(days=100),
            available_at=result.request.as_of - timedelta(days=99),
            promise="Complete acquisition.",
            completed=True,
            completed_at=result.request.as_of - timedelta(days=20),
            completion_available_at=result.request.as_of - timedelta(days=19),
            outcome_at=result.request.as_of - timedelta(days=21),
            outcome_available_at=result.request.as_of - timedelta(days=18),
            outcome_return=0.1,
            evidence_ids=result.evidence_ids,
        )
    action = ManagementActionRecord(
        action_id="future-completion",
        action_type="capital_allocation_promise",
        announced_at=result.request.as_of - timedelta(days=100),
        available_at=result.request.as_of - timedelta(days=99),
        promise="Complete repurchase programme.",
        completed=True,
        completed_at=result.request.as_of + timedelta(days=10),
        completion_available_at=result.request.as_of + timedelta(days=11),
        evidence_ids=result.evidence_ids,
    )
    from aegis.fundamentals import evaluate_management

    projected = evaluate_management(result.statements, [], [action])
    assert projected.capital_allocation_follow_through == 0.0
    request, snapshot, inputs = load_fundamental_fixture(FIXTURES / "cmpd.json")
    values = {
        name: getattr(inputs, name) for name in type(inputs).model_fields if name != "content_hash"
    }
    values["management_actions"] = (action,)
    from aegis.fundamentals.hashing import build_hashed
    from aegis.fundamentals.service import FundamentalResearchInputs

    with pytest.raises(ValueError, match="not point-in-time eligible"):
        build_hashed(FundamentalResearchInputs, **values)
    assert snapshot.ticker == request.ticker


def test_raw_snapshot_rejects_future_fact_and_uses_latest_eligible_revision() -> None:
    request, snapshot, _ = load_fundamental_fixture(FIXTURES / "cmpd.json")
    fact = snapshot.facts[0]
    future = fact.model_copy(
        update={
            "fact_id": "future-fact",
            "available_at": request.as_of + timedelta(seconds=1),
        }
    )
    with pytest.raises(ValueError, match="future facts"):
        raw_snapshot(
            "future",
            request.ticker,
            request.as_of,
            [*snapshot.facts, future],
            ["raw"],
            {"fixture": "1"},
        )
    revenue = next(
        item for item in snapshot.facts if item.concept == "revenue" and item.fiscal_year == 2024
    )
    restated = revenue.model_copy(
        update={
            "fact_id": "restated-revenue",
            "value": revenue.value + 10,
            "revision": 1,
            "supersedes_fact_id": revenue.fact_id,
            "accepted_at": revenue.accepted_at + timedelta(days=1),
            "available_at": revenue.available_at + timedelta(days=1),
        }
    )
    revised = raw_snapshot(
        "revised",
        request.ticker,
        request.as_of,
        [*snapshot.facts, restated],
        ["raw"],
        {"fixture": "1"},
    )
    from aegis.fundamentals.normalization import normalize_statements

    revised_statements = normalize_statements(revised)
    assert revised_statements.reported_periods[-1].revenue == pytest.approx(revenue.value + 10)


def test_contracts_are_strict_and_thesis_ledger_is_tamper_evident(tmp_path: Path) -> None:
    request, _, _ = load_fundamental_fixture(FIXTURES / "cmpd.json")
    with pytest.raises(ValidationError):
        CompanyResearchRequest(**request.model_dump(), unknown="forbidden")
    result = dossier("cmpd")
    assert result.thesis is not None
    ledger = ThesisLedger(tmp_path / "theses.sqlite")
    ledger.append(result.thesis)
    ledger.append(result.thesis)
    assert ledger.latest("CMPD") == result.thesis
    import sqlite3

    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            "UPDATE thesis_versions SET thesis_json = replace(thesis_json, 'active', 'resolved')"
        )
    with pytest.raises((ThesisLedgerError, ValidationError)):
        ledger.history("CMPD")


def test_exact_statement_numbers_reversible_adjustments_and_closed_lineage() -> None:
    request, snapshot, inputs = load_fundamental_fixture(FIXTURES / "cmpd.json")
    assert isinstance(snapshot.facts[0].value, Decimal)
    evidence_fact = next(
        item for item in snapshot.facts if item.fiscal_year == 2024 and item.concept == "revenue"
    )
    adjustment = NormalizationAdjustment(
        adjustment_id="analytical-one-time-2024",
        period_end=evidence_fact.period_end,
        line_item="operating_expenses",
        amount=Decimal("-5.25"),
        reason="remove an evidenced analytical one-time charge",
        evidence_fact_ids=[evidence_fact.fact_id],
    )
    from aegis.fundamentals.normalization import normalize_statements

    statements = normalize_statements(snapshot, [adjustment])
    assert isinstance(statements.reported_periods[-1].revenue, Decimal)
    assert statements.adjusted_periods[-1].operating_expenses == (
        statements.reported_periods[-1].operating_expenses + Decimal("-5.25")
    )
    assert reverse_adjustments(statements) == statements.reported_periods
    adjustment_ids = {item.calculation_id for item in statements.calculation_lineage}
    assert "normalize-adjustment:analytical-one-time-2024" in adjustment_ids
    assert "normalize-adjusted-operating-income:2024-12-31" in adjustment_ids
    dossier_result = _compute_preliminary_research(request, snapshot, inputs)
    lineage_ids = {item.calculation_id for item in dossier_result.calculation_lineage}
    assert lineage_ids == set(dossier_result.calculation_ids)
    assert all(
        set(item.input_calculation_ids).issubset(lineage_ids)
        for item in dossier_result.calculation_lineage
    )


def test_terminal_roic_and_horizon_change_economic_outputs() -> None:
    request, snapshot, inputs = load_fundamental_fixture(FIXTURES / "cmpd.json")
    base = _compute_preliminary_research(request, snapshot, inputs)
    lower_roic_values = {
        name: getattr(inputs, name) for name in type(inputs).model_fields if name != "content_hash"
    }
    lower_roic_values["terminal_roic_by_scenario"] = {
        "bear": 0.08,
        "base": 0.08,
        "bull": 0.08,
    }
    from aegis.fundamentals.hashing import build_hashed
    from aegis.fundamentals.service import FundamentalResearchInputs

    lower_roic_inputs = build_hashed(FundamentalResearchInputs, **lower_roic_values)
    lower_roic = _compute_preliminary_research(request, snapshot, lower_roic_inputs)
    assert lower_roic.dcf["base"].value_per_share < base.dcf["base"].value_per_share
    longer_request = request.model_copy(update={"horizon_days": 730})
    longer = _compute_preliminary_research(
        longer_request,
        snapshot,
        inputs,
    )
    assert base.alpha_forecast.abstained and longer.alpha_forecast.abstained
    assert base.metrics is not None and base.scenario_valuation is not None
    lineage = {item.calculation_id: item for item in base.calculation_lineage}
    longer_lineage = {item.calculation_id: item for item in longer.calculation_lineage}
    assert longer_lineage[
        "fundamental-alpha-v1:calibrated-expected-return"
    ].output_value != pytest.approx(
        lineage["fundamental-alpha-v1:calibrated-expected-return"].output_value
    )
    dividend_id = next(
        item for item in base.metrics.calculation_ids if item.endswith(":dividend_yield")
    )
    assert any("market-price" in item for item in lineage[dividend_id].input_assumption_ids)
    expected_lineage = lineage["fundamental-alpha-v1:calibrated-expected-return"]
    assert dividend_id in expected_lineage.input_calculation_ids
    assert any("horizon-days" in item for item in expected_lineage.input_assumption_ids)
    for calculation_id, item in lineage.items():
        if calculation_id.startswith("fundamental-scorecard-v1:"):
            assert len(item.input_calculation_ids) == len(set(item.input_calculation_ids))
    confidence_lineage = lineage["fundamental-alpha-v1:calibrated-confidence"]
    assert "fundamental-scorecard-v1:uncertainty" in confidence_lineage.input_calculation_ids
    raw_horizon_return = (
        base.scenario_valuation.implied_return
        + base.metrics.dividend_yield * request.horizon_days / 365.0
    )
    raw_annualized = (1 + raw_horizon_return) ** (365.0 / request.horizon_days) - 1
    expected_calibrated = (
        inputs.calibration.return_intercept + inputs.calibration.return_slope * raw_annualized
    )
    assert expected_lineage.output_value == pytest.approx(expected_calibrated)


def test_future_nonfiling_inputs_and_dimension_corruption_halt() -> None:
    request, snapshot, inputs = load_fundamental_fixture(FIXTURES / "cmpd.json")
    _, _, wrong_entity_inputs = load_fundamental_fixture(FIXTURES / "grow.json")
    from aegis.fundamentals.service import FundamentalResearchError

    with pytest.raises(FundamentalResearchError, match="entity/request bound"):
        _compute_preliminary_research(request, snapshot, wrong_entity_inputs)
    grow_record = wrong_entity_inputs.evidence.records[0]
    mixed_evidence = inputs.evidence.model_copy(
        update={"records": [inputs.evidence.records[0], grow_record]}
    )
    mixed_values = {
        name: getattr(inputs, name) for name in type(inputs).model_fields if name != "content_hash"
    }
    mixed_values["evidence"] = mixed_evidence
    mixed_values["field_evidence"] = {
        field_name: [grow_record.evidence_id] for field_name in inputs.field_evidence
    }
    from aegis.fundamentals.hashing import build_hashed
    from aegis.fundamentals.service import FundamentalResearchInputs

    with pytest.raises(ValueError, match="does not resolve issuer"):
        build_hashed(FundamentalResearchInputs, **mixed_values)

    invalid_driver = inputs.drivers[0].model_copy(update={"evidence_ids": ["nonexistent-evidence"]})
    embedded_values = dict(mixed_values)
    embedded_values["evidence"] = inputs.evidence
    embedded_values["field_evidence"] = inputs.field_evidence
    embedded_values["drivers"] = (invalid_driver, *inputs.drivers[1:])
    with pytest.raises(ValueError, match="embedded drivers evidence"):
        build_hashed(FundamentalResearchInputs, **embedded_values)
    live_evidence = inputs.evidence.model_copy(update={"mode": "live_research"})
    mode_values = {
        name: getattr(inputs, name) for name in type(inputs).model_fields if name != "content_hash"
    }
    mode_values["evidence"] = live_evidence
    from aegis.fundamentals.hashing import build_hashed
    from aegis.fundamentals.service import FundamentalResearchInputs

    wrong_mode_inputs = build_hashed(FundamentalResearchInputs, **mode_values)
    with pytest.raises(FundamentalResearchError, match="modes do not match"):
        _compute_preliminary_research(request, snapshot, wrong_mode_inputs)
    poisoned_record = inputs.evidence.records[0].model_copy(
        update={"injection_flags": ["ignore prior rules"]}
    )
    poisoned_evidence = inputs.evidence.model_copy(
        update={"records": [poisoned_record, *inputs.evidence.records[1:]]}
    )
    poison_values = dict(mode_values)
    poison_values["evidence"] = poisoned_evidence.model_copy(update={"mode": "replay"})
    with pytest.raises(ValueError, match="injection flags"):
        build_hashed(FundamentalResearchInputs, **poison_values)
    future_values = {
        name: getattr(inputs, name) for name in type(inputs).model_fields if name != "content_hash"
    }
    future_values["available_at"] = request.as_of + timedelta(seconds=1)
    from aegis.fundamentals.hashing import build_hashed
    from aegis.fundamentals.service import FundamentalResearchInputs

    with pytest.raises(ValidationError, match="availability follows"):
        build_hashed(FundamentalResearchInputs, **future_values)
    bad_fact = snapshot.facts[0].model_copy(update={"unit": "shares"})
    bad_snapshot = raw_snapshot(
        "bad-dimension",
        request.ticker,
        request.as_of,
        [bad_fact, *snapshot.facts[1:]],
        ["raw"],
        {"fixture": "1"},
    )
    from aegis.fundamentals.normalization import StatementNormalizationError, normalize_statements

    with pytest.raises(StatementNormalizationError, match="invalid unit"):
        normalize_statements(bad_snapshot)


def test_saas_and_preprofit_abstention_preserve_original_archetype() -> None:
    request, snapshot, inputs = load_fundamental_fixture(FIXTURES / "cmpd.json")
    from aegis.fundamentals.hashing import build_hashed
    from aegis.fundamentals.service import FundamentalResearchInputs

    for update, expected in (
        ({"subscription_revenue_share": 0.8}, "saas_subscription"),
        ({"profitable": False}, "pre_profit"),
    ):
        values = {
            name: getattr(inputs, name)
            for name in type(inputs).model_fields
            if name != "content_hash"
        }
        values.update(update)
        modified = build_hashed(FundamentalResearchInputs, **values)
        result = _compute_preliminary_research(request, snapshot, modified)
        assert result.abstained
        assert result.archetype.kind == expected
        assert not result.archetype.supported


@pytest.mark.parametrize("fixture_name", ["cmpd", "grow", "warn", "guide", "acqr"])
def test_scorecard_fields_match_same_named_calculation_lineage(fixture_name: str) -> None:
    result = dossier(fixture_name)
    assert result.scorecard is not None
    lineage = {item.calculation_id: item for item in result.calculation_lineage}
    for field_name in (
        "quality",
        "growth",
        "profitability",
        "accounting",
        "balance_sheet",
        "cash_conversion",
        "capital_allocation",
        "management",
        "valuation",
        "expectations_gap",
        "catalyst",
        "uncertainty",
    ):
        calculation = lineage[f"fundamental-scorecard-v1:{field_name}"]
        assert calculation.output_name == field_name
        assert calculation.output_value == pytest.approx(getattr(result.scorecard, field_name))


def test_dcf_sensitivity_cells_have_dependency_complete_exact_lineage() -> None:
    result = dossier("cmpd")
    lineage = {item.calculation_id: item for item in result.calculation_lineage}
    all_point_ids: list[str] = []
    primary_per_share_ids: dict[str, str] = {}
    for scenario, dcf in sorted(result.dcf.items()):
        assert len(dcf.sensitivity) == 9
        primary_id = f"dcf-v1:{dcf.forecast_id}:value_per_share"
        assert primary_id in dcf.calculation_ids
        primary_per_share_ids[scenario] = primary_id
        for point in dcf.sensitivity:
            field_ids = {
                "discount_rate": point.discount_rate_calculation_id,
                "terminal_growth": point.terminal_growth_calculation_id,
                "enterprise_value": point.enterprise_value_calculation_id,
                "equity_value_per_share": point.equity_value_per_share_calculation_id,
            }
            assert len(set(field_ids.values())) == 4
            assert set(field_ids.values()).issubset(dcf.calculation_ids)
            all_point_ids.extend(field_ids.values())
            for field_name, calculation_id in field_ids.items():
                calculation = lineage[calculation_id]
                assert calculation_id in result.calculation_ids
                assert calculation.output_name.endswith(field_name)
                assert Decimal(str(calculation.output_value)) == Decimal(
                    str(getattr(point, field_name))
                )
            enterprise_lineage = lineage[point.enterprise_value_calculation_id]
            assert point.discount_rate_calculation_id in enterprise_lineage.input_calculation_ids
            assert point.terminal_growth_calculation_id in enterprise_lineage.input_calculation_ids
            per_share_lineage = lineage[point.equity_value_per_share_calculation_id]
            assert per_share_lineage.input_calculation_ids == [
                point.enterprise_value_calculation_id
            ]
            assert any("net-debt" in item for item in per_share_lineage.input_assumption_ids)
            assert any("diluted-shares" in item for item in per_share_lineage.input_assumption_ids)
    assert len(all_point_ids) == len(set(all_point_ids))
    scenario_lineage = lineage[result.scenario_valuation.calculation_ids[0]]  # type: ignore[union-attr]
    assert scenario_lineage.input_calculation_ids == [
        primary_per_share_ids[name] for name in ("bear", "base", "bull")
    ]


def test_semantic_calculation_id_selectors_are_order_independent() -> None:
    from aegis.fundamentals.calculation_ids import (
        CalculationIdentityError,
        comparable_calculation_id,
        dcf_calculation_id,
        reverse_dcf_calculation_id,
        scenario_calculation_id,
    )

    result = dossier("cmpd")
    base_dcf = result.dcf["base"]
    reordered_dcf = base_dcf.model_copy(
        update={"calculation_ids": list(reversed(base_dcf.calculation_ids))}
    )
    assert dcf_calculation_id(reordered_dcf, "value_per_share") == (
        f"dcf-v1:{base_dcf.forecast_id}:value_per_share"
    )
    assert result.scenario_valuation is not None
    reordered_scenario = result.scenario_valuation.model_copy(
        update={"calculation_ids": list(reversed(result.scenario_valuation.calculation_ids))}
    )
    assert scenario_calculation_id(reordered_scenario, "implied_return") == (
        "scenario-valuation-v1:implied-return"
    )
    reverse = result.reverse_dcf["revenue_growth"]
    reordered_reverse = reverse.model_copy(
        update={"calculation_ids": list(reversed(reverse.calculation_ids))}
    )
    assert reverse_dcf_calculation_id(reordered_reverse).startswith(
        "reverse-dcf-bisection-v1:revenue-growth"
    )
    assert result.comparables is not None
    reordered_comparables = result.comparables.model_copy(
        update={"calculation_ids": list(reversed(result.comparables.calculation_ids))}
    )
    assert comparable_calculation_id(reordered_comparables, "mid") == (
        "comparable-valuation-v2:implied-mid"
    )
    missing = base_dcf.model_copy(update={"calculation_ids": ["unrelated"]})
    with pytest.raises(CalculationIdentityError, match="exactly one"):
        dcf_calculation_id(missing, "value_per_share")
