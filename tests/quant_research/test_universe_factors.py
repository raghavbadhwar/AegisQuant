from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from aegis.contracts.quant import FactorDefinition
from aegis.quant_research.diagnostics import (
    DiagnosticObservation,
    build_factor_evaluation,
    compute_factor_diagnostics,
)
from aegis.quant_research.factors import (
    DuplicateFactorError,
    FactorInputRecord,
    FactorRegistry,
    evaluate_factor,
)
from aegis.quant_research.hashing import build_hashed
from aegis.quant_research.universe import (
    RawUniverseRecord,
    UniverseRules,
    build_universe_snapshot,
)

NOW = datetime(2025, 6, 30, tzinfo=UTC)
LIMITATION = "Fixed test fixture; not a survivorship-free production security master."
RULES = UniverseRules("universe-rules-v1", 1_000_000.0, 100_000_000.0, 0.9)


def raw(ticker: str, **updates: object) -> RawUniverseRecord:
    values: dict[str, object] = {
        "member_id": f"member-{ticker.lower()}-v1",
        "ticker": ticker,
        "available_at": NOW - timedelta(days=2),
        "listing_date": date(2020, 1, 1),
        "delisting_date": None,
        "listing_status": "listed",
        "average_daily_dollar_volume": 10_000_000.0,
        "market_cap": 1_000_000_000.0,
        "sector": "Technology",
        "industry": "Software",
        "source_ids": (f"source-{ticker.lower()}",),
    }
    values.update(updates)
    return RawUniverseRecord(**values)  # type: ignore[arg-type]


def snapshot(records: tuple[RawUniverseRecord, ...]):  # type: ignore[no-untyped-def]
    return build_universe_snapshot(
        records,
        snapshot_id="snapshot-test-v1",
        universe_id="universe-test-v1",
        as_of=NOW,
        rules=RULES,
        fixed_fixture=True,
        limitation=LIMITATION,
    )


def definition(factor_id: str = "quality-core-v1") -> FactorDefinition:
    return build_hashed(
        FactorDefinition,
        factor_id=factor_id,
        name="Quality",
        family="quality",
        economic_rationale="Profitable, conservatively financed firms may persist.",
        deterministic_formula="(return_on_equity + gross_profitability - debt_to_assets) / 3",
        lookback_days=365,
        lag_days=1,
        universe_id="universe-test-v1",
        neutralization=(),
        horizon_days=20,
        commission_bps=2.0,
        slippage_bps=3.0,
    )


def test_universe_filters_future_revisions_and_emits_stable_complete_reasons() -> None:
    weak = raw(
        "BAD",
        member_id="member-bad-v1",
        listing_status="halted",
        average_daily_dollar_volume=1.0,
        market_cap=2.0,
        sector=None,
        industry=None,
        corporate_action_status="pending_merger",
        data_completeness=0.2,
        borrow_eligible=False,
        outside_mandate=True,
    )
    baseline = snapshot((raw("AAA"), weak))
    future = raw(
        "AAA",
        available_at=NOW + timedelta(seconds=1),
        average_daily_dollar_volume=0.0,
        revision=2,
    )
    mutated = snapshot((future, weak, raw("AAA")))

    assert mutated == baseline
    assert baseline.decisions[0].reasons == ("eligible",)
    assert baseline.decisions[1].reasons == (
        "not_listed",
        "insufficient_liquidity",
        "insufficient_market_cap",
        "missing_sector_industry",
        "corporate_action_restricted",
        "incomplete_data",
        "borrow_unavailable",
        "outside_mandate",
    )
    with pytest.raises(ValueError, match="explicit limitation"):
        build_universe_snapshot(
            (raw("AAA"),),
            snapshot_id="snapshot-test-v1",
            universe_id="universe-test-v1",
            as_of=NOW,
            rules=RULES,
            fixed_fixture=True,
            limitation=None,
        )


def test_immutable_registry_lagged_revisions_and_fail_closed_abstention() -> None:
    factor = definition()
    registry = FactorRegistry().register(factor)
    assert FactorRegistry().definitions == ()
    assert registry.get(factor.factor_id) is factor
    with pytest.raises(DuplicateFactorError):
        registry.register(factor)

    inputs = (
        *(
            FactorInputRecord(
                "AAA",
                field,
                value,
                NOW - timedelta(days=30),
                NOW - timedelta(days=2),
                source_id=f"source-{field}",
            )
            for field, value in (
                ("return_on_equity", 0.3),
                ("gross_profitability", 0.6),
                ("debt_to_assets", 0.15),
            )
        ),
        FactorInputRecord(
            "AAA",
            "return_on_equity",
            99.0,
            NOW - timedelta(days=30),
            NOW,
            revision=2,
            source_id="future-revision",
        ),
    )
    universe = snapshot((raw("AAA"), raw("MISS")))
    run = evaluate_factor(
        factor,
        snapshot=universe,
        inputs=inputs,
        calculation_id="calculation-quality-v1",
    )
    assert run.observations[0].value == pytest.approx(0.25)
    assert tuple(item.ticker for item in run.abstentions) == ("MISS",)
    with pytest.raises(ValueError, match="abstained"):
        evaluate_factor(
            factor,
            snapshot=universe,
            inputs=inputs,
            calculation_id="calculation-quality-v1",
            fail_on_missing=True,
        )


def diagnostic_rows() -> tuple[DiagnosticObservation, ...]:
    rows = []
    for period, (values, returns) in enumerate(
        (
            ((1.0, 2.0, 3.0, 4.0), (0.0, 1.0, 2.0, 3.0)),
            ((4.0, 3.0, 2.0, 1.0), (4.0, 3.0, 2.0, 1.0)),
        )
    ):
        as_of = NOW + timedelta(days=period * 10)
        for index, ticker in enumerate(("AAA", "BBB", "CCC", "DDD")):
            rows.append(
                DiagnosticObservation(
                    observation_id=f"diagnostic-{period}-{ticker.lower()}-v1",
                    universe_snapshot_id=f"snapshot-{period + 1}-v1",
                    calculation_id="calculation-diagnostic-v1",
                    ticker=ticker,
                    as_of=as_of,
                    feature_available_at=as_of - timedelta(days=1),
                    return_start_at=as_of,
                    return_end_at=as_of + timedelta(days=5),
                    factor_value=values[index],
                    forward_return=returns[index],
                    sector="Technology" if index % 2 == 0 else "Financials",
                    market_cap=100.0 * (index + 1),
                    average_daily_dollar_volume=1_000_000.0 * (index + 1),
                    subperiod=f"half-{period + 1}",
                    regime="calm" if period == 0 else "stress",
                    decay_returns=((5, values[index]),),
                    comparison_factors=(("momentum-core-v1", values[index]),),
                )
            )
    return tuple(rows)


def test_hand_calculated_full_diagnostics_are_permutation_invariant_and_causal() -> None:
    rows = diagnostic_rows()
    diagnostics = compute_factor_diagnostics(
        rows,
        quantiles=2,
        commission_bps=4.0,
        slippage_bps=6.0,
    )
    permuted = compute_factor_diagnostics(
        tuple(reversed(rows)),
        quantiles=2,
        commission_bps=4.0,
        slippage_bps=6.0,
    )
    assert diagnostics == permuted
    assert diagnostics.information_coefficient == pytest.approx(1.0)
    assert diagnostics.rank_information_coefficient == pytest.approx(1.0)
    assert diagnostics.quantile_returns == pytest.approx((1.0, 3.0))
    assert diagnostics.long_short_return == pytest.approx(2.0)
    assert diagnostics.monotonicity == pytest.approx(1.0)
    assert diagnostics.turnover == pytest.approx(2.0)
    assert diagnostics.autocorrelation == pytest.approx(-1.0)
    assert diagnostics.gross_return == pytest.approx(2.0)
    assert diagnostics.cost_adjusted_return == pytest.approx(1.998)
    assert diagnostics.capacity == pytest.approx(10_000.0)
    assert diagnostics.decay == {5: pytest.approx(1.0)}
    assert diagnostics.factor_correlations == {"momentum-core-v1": pytest.approx(1.0)}
    assert diagnostics.crowding_score == pytest.approx(1.0)
    assert diagnostics.subperiod_returns == {"half-1": 2.0, "half-2": 2.0}
    assert diagnostics.regime_returns == {"calm": 2.0, "stress": 2.0}

    evaluation = build_factor_evaluation(
        evaluation_id="evaluation-quality-v1",
        factor_id="quality-core-v1",
        observations=rows,
        evaluation_as_of=max(row.return_end_at for row in rows),
        diagnostics=diagnostics,
    )
    assert len(evaluation.observation_ids) == 8

    first = rows[0]
    with pytest.raises(ValueError, match="unavailable"):
        replace(first, feature_available_at=first.as_of + timedelta(seconds=1))
