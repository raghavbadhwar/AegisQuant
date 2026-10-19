from datetime import timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pytest
from pydantic import ValidationError

from aegisquant.contracts.research import CorporateActionKind
from aegisquant.contracts.risk import OrderSide
from aegisquant.quant.multi_period import (
    MultiPeriodCaseSpec,
    multi_period_holdout_digest,
    run_multi_period_case,
    verify_multi_period_report,
)
from aegisquant.security.digests import digest_canonical

FIXTURE = Path("data/fixtures/cases/multi_period_control.json")


def spec() -> MultiPeriodCaseSpec:
    return MultiPeriodCaseSpec.model_validate_json(FIXTURE.read_bytes())


def test_multi_period_fixture_exercises_real_pit_accounting() -> None:
    value = spec()
    report = run_multi_period_case(value)

    assert len(report.periods) == 6
    assert {action.kind for period in report.periods for action in period.applied_actions} == {
        CorporateActionKind.SPLIT,
        CorporateActionKind.CASH_DIVIDEND,
        CorporateActionKind.DELISTING_CASH,
    }
    assert tuple(
        order_id for period in report.periods for order_id in period.stale_rejected_order_ids
    ) == ("p1-stale-bbb",)
    assert tuple(
        order_id for period in report.periods for order_id in period.unfilled_order_ids
    ) == ("p2-limit-aaa",)
    assert {fill.side for period in report.periods for fill in period.fills} == {
        OrderSide.BUY,
        OrderSide.SELL,
    }
    assert (
        sum(
            (fill.transaction_cost for period in report.periods for fill in period.fills),
            Decimal(0),
        )
        > 0
    )
    first_fill = report.periods[0].fills[0]
    prior_close = max(
        bar.close_price
        for bar in value.bars
        if bar.instrument_id == first_fill.instrument_id
        and bar.tradable_at < report.periods[0].decision_at
    )
    assert first_fill.price == Decimal("12")
    assert prior_close == Decimal("10")
    assert report.final_cash == Decimal("1049.0975")
    assert report.final_positions == ()
    assert report.final_nav == Decimal("1049.0975")
    benchmark_bars = tuple(
        bar for bar in value.bars if bar.instrument_id == value.benchmark_instrument_id
    )
    initial_benchmark = max(
        (bar for bar in benchmark_bars if bar.tradable_at <= value.periods[0].decision_at),
        key=lambda bar: bar.tradable_at,
    ).close_price
    final_benchmark = max(
        (bar for bar in benchmark_bars if bar.tradable_at <= value.periods[-1].fill_at),
        key=lambda bar: bar.tradable_at,
    ).close_price
    assert report.benchmark_return == final_benchmark / initial_benchmark - Decimal(1)
    assert report.benchmark_return == Decimal("0.12")
    assert type(report).model_validate_json(report.model_dump_json()) == report
    assert verify_multi_period_report(value, report)


def test_evaluation_is_locked_nonoverlapping_and_conservative() -> None:
    value = spec()
    report = run_multi_period_case(value)

    assert report.walk_forward_windows == (
        (0, 2, 2, 3),
        (1, 3, 3, 4),
        (2, 4, 4, 5),
        (3, 5, 5, 6),
    )
    test_ranges = tuple((item[2], item[3]) for item in report.walk_forward_windows)
    assert all(left[1] <= right[0] for left, right in pairwise(test_ranges))
    assert report.locked_holdout_digest == value.locked_holdout_digest
    assert len(report.holdout_returns) == 2
    assert report.placebo_returns == (Decimal(0),) * len(report.strategy_returns)
    assert report.performance.observations == 6
    assert report.performance.sufficient_evidence is False

    tampered = report.model_copy(update={"final_nav": report.final_nav + Decimal("0.001")})
    tampered = tampered.model_copy(
        update={
            "report_digest": digest_canonical(
                tampered.model_dump(mode="python", exclude={"report_digest"})
            )
        }
    )
    assert not verify_multi_period_report(value, tampered)

    raw = value.model_dump(mode="python")
    with pytest.raises(ValidationError, match="holdout"):
        MultiPeriodCaseSpec.model_validate(raw | {"locked_holdout_digest": "sha256:" + "f" * 64})
    with pytest.raises(ValidationError, match="holdout"):
        MultiPeriodCaseSpec.model_validate(
            raw
            | {
                "bars": (
                    value.bars[0].model_copy(update={"close_price": Decimal("10.01")}),
                    *value.bars[1:],
                )
            }
        )
    with pytest.raises(ValidationError, match="holdout"):
        MultiPeriodCaseSpec.model_validate(raw | {"initial_cash": value.initial_cash + 1})
    changed_first = value.periods[0].model_copy(
        update={
            "orders": (
                value.periods[0].orders[0].model_copy(update={"quantity": Decimal("11")}),
                *value.periods[0].orders[1:],
            )
        }
    )
    with pytest.raises(ValidationError, match="holdout"):
        MultiPeriodCaseSpec.model_validate(raw | {"periods": (changed_first, *value.periods[1:])})


@pytest.mark.parametrize("period_index", [2, 4])
def test_open_position_rejects_cross_version_buy_or_sell(period_index: int) -> None:
    value = spec()
    period = value.periods[period_index]
    changed_order = period.orders[0].model_copy(update={"instrument_version": "aaa-v2"})
    periods = tuple(
        item.model_copy(update={"orders": (changed_order,)}) if item is period else item
        for item in value.periods
    )
    current = max(
        (
            item
            for item in value.bars
            if item.instrument_id == "AAA" and item.tradable_at <= period.decision_at
        ),
        key=lambda item: item.tradable_at,
    )
    bars = (
        *tuple(
            item.model_copy(update={"instrument_version": "aaa-v2"})
            if item.instrument_id == "AAA" and item.tradable_at == period.fill_at
            else item
            for item in value.bars
        ),
        current.model_copy(update={"instrument_version": "aaa-v2"}),
    )
    holdout_ids = set(value.holdout_period_ids)
    holdout = tuple(item for item in periods if item.period_id in holdout_ids)
    changed = MultiPeriodCaseSpec.model_validate(
        value.model_dump(mode="python")
        | {
            "bars": bars,
            "periods": periods,
            "locked_holdout_digest": multi_period_holdout_digest(
                holdout_periods=holdout,
                state_forming_periods=periods,
                initial_cash=value.initial_cash,
                bars=bars,
                corporate_actions=value.corporate_actions,
                transaction_cost_rate=value.transaction_cost_rate,
                max_bar_age_seconds=value.max_bar_age_seconds,
                benchmark_instrument_id=value.benchmark_instrument_id,
            ),
        }
    )

    with pytest.raises(ValueError, match="order version"):
        run_multi_period_case(changed)


def test_delisted_security_version_cannot_be_reacquired() -> None:
    value = spec()
    target = value.periods[4]
    repurchase = (
        value.periods[0].orders[1].model_copy(update={"client_order_id": "p5-repurchase-del"})
    )
    periods = tuple(
        item.model_copy(update={"orders": (*item.orders, repurchase)}) if item is target else item
        for item in value.periods
    )
    prior_bar = max(
        (
            item
            for item in value.bars
            if item.instrument_id == "AAA" and item.tradable_at < target.decision_at
        ),
        key=lambda item: item.tradable_at,
    ).model_copy(update={"instrument_id": "DEL", "instrument_version": "del-v1"})
    fill_bar = next(
        item
        for item in value.bars
        if item.instrument_id == "AAA" and item.tradable_at == target.fill_at
    ).model_copy(update={"instrument_id": "DEL", "instrument_version": "del-v1"})
    bars = (*value.bars, prior_bar, fill_bar)
    holdout_ids = set(value.holdout_period_ids)
    holdout = tuple(item for item in periods if item.period_id in holdout_ids)
    changed = MultiPeriodCaseSpec.model_validate(
        value.model_dump(mode="python")
        | {
            "bars": bars,
            "periods": periods,
            "locked_holdout_digest": multi_period_holdout_digest(
                holdout_periods=holdout,
                state_forming_periods=periods,
                initial_cash=value.initial_cash,
                bars=bars,
                corporate_actions=value.corporate_actions,
                transaction_cost_rate=value.transaction_cost_rate,
                max_bar_age_seconds=value.max_bar_age_seconds,
                benchmark_instrument_id=value.benchmark_instrument_id,
            ),
        }
    )

    with pytest.raises(ValueError, match="terminally delisted"):
        run_multi_period_case(changed)


def test_later_action_in_same_batch_cannot_follow_delisting() -> None:
    value = spec()
    delisting = next(
        item for item in value.corporate_actions if item.kind == CorporateActionKind.DELISTING_CASH
    )
    late_dividend = delisting.model_copy(
        update={
            "kind": CorporateActionKind.CASH_DIVIDEND,
            "effective_at": delisting.effective_at + timedelta(minutes=30),
            "available_at": delisting.available_at + timedelta(minutes=30),
            "cash_per_share": Decimal("0.1"),
        }
    )
    actions = (*value.corporate_actions, late_dividend)
    holdout_ids = set(value.holdout_period_ids)
    holdout = tuple(item for item in value.periods if item.period_id in holdout_ids)
    changed = MultiPeriodCaseSpec.model_validate(
        value.model_dump(mode="python")
        | {
            "corporate_actions": actions,
            "locked_holdout_digest": multi_period_holdout_digest(
                holdout_periods=holdout,
                state_forming_periods=value.periods,
                initial_cash=value.initial_cash,
                bars=value.bars,
                corporate_actions=actions,
                transaction_cost_rate=value.transaction_cost_rate,
                max_bar_age_seconds=value.max_bar_age_seconds,
                benchmark_instrument_id=value.benchmark_instrument_id,
            ),
        }
    )

    with pytest.raises(ValueError, match="terminally delisted"):
        run_multi_period_case(changed)
