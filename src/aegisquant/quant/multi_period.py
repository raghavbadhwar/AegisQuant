"""Deterministic multi-period point-in-time paper evaluation."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import (
    FixedDecimal,
    Identifier,
    Sha256Digest,
    StrictModel,
    require_utc,
)
from aegisquant.contracts.research import (
    CorporateAction,
    CorporateActionKind,
    MarketBar,
    PaperFill,
    PerformanceReport,
    PositionLedgerEntry,
)
from aegisquant.contracts.risk import OrderIntent, OrderSide, OrderType, TimeInForce
from aegisquant.quant.metrics import performance_report, walk_forward_windows
from aegisquant.quant.pit import apply_available_corporate_actions, marked_nav, next_market_bar
from aegisquant.security.digests import digest_canonical


class RebalancePeriod(StrictModel):
    schema_version: Literal[1] = 1
    period_id: Identifier
    decision_at: datetime
    fill_at: datetime
    orders: tuple[OrderIntent, ...] = ()

    @field_validator("decision_at", "fill_at", mode="before")
    @classmethod
    def times_are_utc(cls, value: object) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise ValueError("rebalance times must be UTC datetimes")
        return require_utc(value)

    @field_validator("orders", mode="before")
    @classmethod
    def parse_orders(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        parsed: list[OrderIntent] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("orders must be JSON objects")
            data = dict(item)
            data["side"] = OrderSide(data["side"])
            data["order_type"] = OrderType(data["order_type"])
            data["time_in_force"] = TimeInForce(data["time_in_force"])
            parsed.append(OrderIntent.model_validate(data))
        return tuple(parsed)

    @model_validator(mode="after")
    def chronology_and_ids(self) -> RebalancePeriod:
        if self.fill_at <= self.decision_at:
            raise ValueError("fill_at must follow decision_at")
        order_ids = [item.client_order_id for item in self.orders]
        if len(set(order_ids)) != len(order_ids):
            raise ValueError("period order IDs must be unique")
        return self


def multi_period_holdout_digest(
    *,
    holdout_periods: tuple[RebalancePeriod, ...],
    state_forming_periods: tuple[RebalancePeriod, ...],
    initial_cash: Decimal,
    bars: tuple[MarketBar, ...],
    corporate_actions: tuple[CorporateAction, ...],
    transaction_cost_rate: Decimal,
    max_bar_age_seconds: int,
    benchmark_instrument_id: str,
) -> str:
    return digest_canonical(
        {
            "holdout_periods": holdout_periods,
            "state_forming_periods": state_forming_periods,
            "initial_cash": initial_cash,
            "bars": bars,
            "corporate_actions": corporate_actions,
            "transaction_cost_rate": transaction_cost_rate,
            "max_bar_age_seconds": max_bar_age_seconds,
            "benchmark_instrument_id": benchmark_instrument_id,
        }
    )


class MultiPeriodCaseSpec(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    initial_cash: FixedDecimal
    transaction_cost_rate: FixedDecimal
    max_bar_age_seconds: int = Field(ge=1)
    benchmark_instrument_id: Identifier
    bars: tuple[MarketBar, ...]
    corporate_actions: tuple[CorporateAction, ...] = ()
    periods: tuple[RebalancePeriod, ...] = Field(min_length=6)
    holdout_period_ids: tuple[Identifier, ...] = Field(min_length=1)
    locked_holdout_digest: Sha256Digest
    walk_forward_training_periods: int = Field(ge=1)
    walk_forward_test_periods: int = Field(ge=1)
    walk_forward_step: int = Field(ge=1)
    annualization_periods: int = Field(default=252, ge=1)
    strategy_trials: int = Field(default=1, ge=1)

    @field_validator("bars", mode="before")
    @classmethod
    def parse_bars(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        parsed: list[MarketBar] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("bars must be JSON objects")
            data = dict(item)
            for field in ("observed_at", "available_at", "tradable_at"):
                if isinstance(data.get(field), str):
                    data[field] = datetime.fromisoformat(data[field].replace("Z", "+00:00"))
            parsed.append(MarketBar.model_validate(data))
        return tuple(parsed)

    @field_validator("corporate_actions", mode="before")
    @classmethod
    def parse_actions(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        parsed: list[CorporateAction] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("corporate actions must be JSON objects")
            data = dict(item)
            data["kind"] = CorporateActionKind(data["kind"])
            parsed.append(CorporateAction.model_validate(data))
        return tuple(parsed)

    @field_validator("periods", mode="before")
    @classmethod
    def parse_periods(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return tuple(RebalancePeriod.model_validate(item) for item in value)

    @field_validator("holdout_period_ids", mode="before")
    @classmethod
    def parse_holdout_ids(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def fixture_is_locked(self) -> MultiPeriodCaseSpec:
        if self.initial_cash <= 0 or self.transaction_cost_rate < 0:
            raise ValueError("cash must be positive and transaction costs nonnegative")
        period_ids = [item.period_id for item in self.periods]
        if len(set(period_ids)) != len(period_ids):
            raise ValueError("period IDs must be unique")
        order_ids = [order.client_order_id for period in self.periods for order in period.orders]
        if len(set(order_ids)) != len(order_ids):
            raise ValueError("order IDs must be unique across all periods")
        action_digests = [digest_canonical(item) for item in self.corporate_actions]
        if len(set(action_digests)) != len(action_digests):
            raise ValueError("corporate actions must be unique")
        if tuple(sorted(self.periods, key=lambda item: item.decision_at)) != self.periods:
            raise ValueError("periods must be ordered by decision time")
        if any(left.fill_at >= right.decision_at for left, right in pairwise(self.periods)):
            raise ValueError("rebalance periods must not overlap")
        holdout_ids = set(self.holdout_period_ids)
        if len(holdout_ids) != len(self.holdout_period_ids) or not holdout_ids <= set(period_ids):
            raise ValueError("holdout period IDs must be unique fixture periods")
        holdout = tuple(item for item in self.periods if item.period_id in holdout_ids)
        last_holdout_index = max(
            index for index, item in enumerate(self.periods) if item.period_id in holdout_ids
        )
        if (
            multi_period_holdout_digest(
                holdout_periods=holdout,
                state_forming_periods=self.periods[: last_holdout_index + 1],
                initial_cash=self.initial_cash,
                bars=self.bars,
                corporate_actions=self.corporate_actions,
                transaction_cost_rate=self.transaction_cost_rate,
                max_bar_age_seconds=self.max_bar_age_seconds,
                benchmark_instrument_id=self.benchmark_instrument_id,
            )
            != self.locked_holdout_digest
        ):
            raise ValueError("locked_holdout_digest does not bind the holdout periods")
        walk_forward_windows(
            len(self.periods),
            training_observations=self.walk_forward_training_periods,
            test_observations=self.walk_forward_test_periods,
            step=self.walk_forward_step,
        )
        return self


class PeriodResult(StrictModel):
    schema_version: Literal[1] = 1
    period_id: Identifier
    decision_at: datetime
    fill_at: datetime
    applied_actions: tuple[CorporateAction, ...]
    fills: tuple[PaperFill, ...]
    unfilled_order_ids: tuple[Identifier, ...]
    stale_rejected_order_ids: tuple[Identifier, ...]
    cash: FixedDecimal
    positions: tuple[PositionLedgerEntry, ...]
    nav: FixedDecimal
    period_return: FixedDecimal
    benchmark_return: FixedDecimal

    @field_validator(
        "applied_actions",
        "fills",
        "unfilled_order_ids",
        "stale_rejected_order_ids",
        "positions",
        mode="before",
    )
    @classmethod
    def json_arrays_are_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("decision_at", "fill_at", mode="before")
    @classmethod
    def times_are_utc(cls, value: object) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise ValueError("period result times must be UTC datetimes")
        return require_utc(value)


class MultiPeriodCaseReport(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    spec_digest: Sha256Digest
    periods: tuple[PeriodResult, ...]
    final_cash: FixedDecimal
    final_positions: tuple[PositionLedgerEntry, ...]
    final_nav: FixedDecimal
    benchmark_return: FixedDecimal
    strategy_returns: tuple[FixedDecimal, ...]
    benchmark_returns: tuple[FixedDecimal, ...]
    walk_forward_windows: tuple[tuple[int, int, int, int], ...]
    locked_holdout_digest: Sha256Digest
    holdout_returns: tuple[FixedDecimal, ...]
    placebo_returns: tuple[FixedDecimal, ...]
    performance: PerformanceReport
    report_digest: Sha256Digest

    @field_validator(
        "periods",
        "final_positions",
        "strategy_returns",
        "benchmark_returns",
        "holdout_returns",
        "placebo_returns",
        mode="before",
    )
    @classmethod
    def json_arrays_are_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("walk_forward_windows", mode="before")
    @classmethod
    def parse_windows(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return tuple(tuple(item) if isinstance(item, list) else item for item in value)


def _latest_bar(
    bars: tuple[MarketBar, ...],
    instrument_id: str,
    at: datetime,
    instrument_version: str | None = None,
) -> MarketBar:
    eligible = tuple(
        item
        for item in bars
        if item.instrument_id == instrument_id
        and (instrument_version is None or item.instrument_version == instrument_version)
        and item.available_at <= at
        and item.tradable_at <= at
    )
    if not eligible:
        raise ValueError(f"no point-in-time bar for {instrument_id}")
    return max(eligible, key=lambda item: (item.available_at, item.observed_at, item.tradable_at))


def _stale(bar: MarketBar, at: datetime, max_age_seconds: int) -> bool:
    return at - bar.available_at > timedelta(seconds=max_age_seconds)


def _limit_allows(order: OrderIntent, price: Decimal) -> bool:
    return (
        order.order_type == OrderType.MARKET
        or (
            order.side == OrderSide.BUY
            and order.limit_price is not None
            and price <= order.limit_price
        )
        or (
            order.side == OrderSide.SELL
            and order.limit_price is not None
            and price >= order.limit_price
        )
    )


def _report_digest(report: MultiPeriodCaseReport) -> str:
    return digest_canonical(report.model_dump(mode="python", exclude={"report_digest"}))


def run_multi_period_case(spec: MultiPeriodCaseSpec) -> MultiPeriodCaseReport:
    cash = spec.initial_cash
    quantities: dict[str, Decimal] = {}
    versions: dict[str, str] = {}
    applied_action_digests: set[str] = set()
    terminally_delisted: set[tuple[str, str]] = set()
    period_results: list[PeriodResult] = []
    strategy_returns: list[Decimal] = []
    benchmark_returns: list[Decimal] = []
    previous_nav = spec.initial_cash
    initial_benchmark_bar = _latest_bar(
        spec.bars, spec.benchmark_instrument_id, spec.periods[0].decision_at
    )
    if _stale(
        initial_benchmark_bar,
        spec.periods[0].decision_at,
        spec.max_bar_age_seconds,
    ):
        raise ValueError("benchmark requires a current point-in-time bar")
    previous_benchmark = initial_benchmark_bar.close_price
    initial_benchmark = previous_benchmark

    for period in spec.periods:
        due_actions = tuple(
            action
            for action in sorted(
                spec.corporate_actions, key=lambda item: (item.effective_at, item.instrument_id)
            )
            if action.effective_at <= period.decision_at
            and action.available_at <= period.decision_at
            and digest_canonical(action) not in applied_action_digests
        )
        for action in due_actions:
            identity = (action.instrument_id, action.instrument_version)
            if identity in terminally_delisted:
                raise ValueError("corporate action targets a terminally delisted security")
            if (
                quantities.get(action.instrument_id, Decimal(0)) > 0
                and versions.get(action.instrument_id) != action.instrument_version
            ):
                raise ValueError("corporate action version does not bind the open position")
            quantities, cash = apply_available_corporate_actions(
                quantities, cash, (action,), as_of=period.decision_at
            )
            applied_action_digests.add(digest_canonical(action))
            if action.kind == CorporateActionKind.DELISTING_CASH:
                versions.pop(action.instrument_id, None)
                terminally_delisted.add(identity)

        fills: list[PaperFill] = []
        unfilled: list[str] = []
        stale_rejected: list[str] = []
        for order in period.orders:
            if (order.instrument_id, order.instrument_version) in terminally_delisted:
                raise ValueError("order targets a terminally delisted security")
            try:
                current = _latest_bar(
                    spec.bars,
                    order.instrument_id,
                    period.decision_at,
                    order.instrument_version,
                )
            except ValueError:
                stale_rejected.append(order.client_order_id)
                continue
            if _stale(current, period.decision_at, spec.max_bar_age_seconds):
                stale_rejected.append(order.client_order_id)
                continue
            bar = next_market_bar(
                spec.bars, instrument_id=order.instrument_id, after=period.decision_at
            )
            if (
                bar.tradable_at != period.fill_at
                or bar.instrument_version != order.instrument_version
            ):
                raise ValueError("fill bar does not bind the scheduled order")
            if not _limit_allows(order, bar.open_price):
                unfilled.append(order.client_order_id)
                continue
            notional = order.quantity * bar.open_price
            cost = notional * spec.transaction_cost_rate
            held = quantities.get(order.instrument_id, Decimal(0))
            if held > 0 and versions.get(order.instrument_id) != order.instrument_version:
                raise ValueError("order version does not bind the open position")
            if order.side == OrderSide.BUY:
                if cash < notional + cost:
                    raise ValueError("multi-period paper account has insufficient cash")
                cash -= notional + cost
                quantities[order.instrument_id] = held + order.quantity
            else:
                if held < order.quantity:
                    raise ValueError("multi-period paper account cannot create a short position")
                cash += notional - cost
                quantities[order.instrument_id] = held - order.quantity
            versions[order.instrument_id] = order.instrument_version
            fills.append(
                PaperFill(
                    client_order_id=order.client_order_id,
                    instrument_id=order.instrument_id,
                    instrument_version=order.instrument_version,
                    side=order.side,
                    quantity=order.quantity,
                    price=bar.open_price,
                    transaction_cost=cost,
                    filled_at=bar.tradable_at,
                    market_data_digest=digest_canonical(bar),
                )
            )

        quantities = {key: value for key, value in quantities.items() if value > 0}
        versions = {key: value for key, value in versions.items() if key in quantities}
        marks: dict[str, Decimal] = {}
        positions: list[PositionLedgerEntry] = []
        for instrument_id, quantity in sorted(quantities.items()):
            if quantity <= 0:
                continue
            bar = _latest_bar(spec.bars, instrument_id, period.fill_at, versions[instrument_id])
            if _stale(bar, period.fill_at, spec.max_bar_age_seconds):
                raise ValueError("open position has a stale point-in-time mark")
            marks[instrument_id] = bar.close_price
            positions.append(
                PositionLedgerEntry(
                    instrument_id=instrument_id,
                    instrument_version=versions[instrument_id],
                    quantity=quantity,
                    mark_price=bar.close_price,
                    marked_at=period.fill_at,
                    source_digest=digest_canonical(bar),
                )
            )
        nav = marked_nav(cash, quantities, marks)
        period_return = nav / previous_nav - Decimal(1)
        benchmark_bar = _latest_bar(spec.bars, spec.benchmark_instrument_id, period.fill_at)
        if _stale(benchmark_bar, period.fill_at, spec.max_bar_age_seconds):
            raise ValueError("benchmark requires a current point-in-time bar")
        benchmark_mark = benchmark_bar.close_price
        benchmark_period_return = benchmark_mark / previous_benchmark - Decimal(1)
        strategy_returns.append(period_return)
        benchmark_returns.append(benchmark_period_return)
        period_results.append(
            PeriodResult(
                period_id=period.period_id,
                decision_at=period.decision_at,
                fill_at=period.fill_at,
                applied_actions=due_actions,
                fills=tuple(fills),
                unfilled_order_ids=tuple(unfilled),
                stale_rejected_order_ids=tuple(stale_rejected),
                cash=cash,
                positions=tuple(positions),
                nav=nav,
                period_return=period_return,
                benchmark_return=benchmark_period_return,
            )
        )
        previous_nav = nav
        previous_benchmark = benchmark_mark

    windows = walk_forward_windows(
        len(spec.periods),
        training_observations=spec.walk_forward_training_periods,
        test_observations=spec.walk_forward_test_periods,
        step=spec.walk_forward_step,
    )
    holdout_ids = set(spec.holdout_period_ids)
    returns = tuple(strategy_returns)
    placebo = (Decimal(0),) * len(returns)
    holdout_return_values = tuple(
        item.period_return for item in period_results if item.period_id in holdout_ids
    )
    placeholder = "sha256:" + "0" * 64
    report = MultiPeriodCaseReport(
        tenant_id=spec.tenant_id,
        case_id=spec.case_id,
        spec_digest=digest_canonical(spec),
        periods=tuple(period_results),
        final_cash=cash,
        final_positions=period_results[-1].positions,
        final_nav=period_results[-1].nav,
        benchmark_return=previous_benchmark / initial_benchmark - Decimal(1),
        strategy_returns=returns,
        benchmark_returns=tuple(benchmark_returns),
        walk_forward_windows=windows,
        locked_holdout_digest=spec.locked_holdout_digest,
        holdout_returns=holdout_return_values,
        placebo_returns=placebo,
        performance=performance_report(
            returns,
            annualization_periods=spec.annualization_periods,
            strategy_trials=spec.strategy_trials,
            out_of_sample_fold_returns=tuple(
                returns[test_start:test_end] for _, _, test_start, test_end in windows
            ),
            holdout_returns=holdout_return_values,
            benchmark_returns=tuple(benchmark_returns),
            placebo_returns=placebo,
        ),
        report_digest=placeholder,
    )
    return report.model_copy(update={"report_digest": _report_digest(report)})


def verify_multi_period_report(spec: MultiPeriodCaseSpec, report: MultiPeriodCaseReport) -> bool:
    """Recompute execution eligibility and accounting without trusting report totals."""

    try:
        if (
            report.tenant_id != spec.tenant_id
            or report.case_id != spec.case_id
            or report.spec_digest != digest_canonical(spec)
            or report.locked_holdout_digest != spec.locked_holdout_digest
            or report.report_digest != _report_digest(report)
            or len(report.periods) != len(spec.periods)
        ):
            return False
        cash = spec.initial_cash
        quantities: dict[str, Decimal] = {}
        versions: dict[str, str] = {}
        applied: set[str] = set()
        terminally_delisted: set[tuple[str, str]] = set()
        previous_nav = spec.initial_cash
        initial_benchmark_bar = _latest_bar(
            spec.bars, spec.benchmark_instrument_id, spec.periods[0].decision_at
        )
        if _stale(
            initial_benchmark_bar,
            spec.periods[0].decision_at,
            spec.max_bar_age_seconds,
        ):
            return False
        previous_benchmark = initial_benchmark_bar.close_price
        initial_benchmark = previous_benchmark
        strategy_returns: list[Decimal] = []
        benchmark_returns: list[Decimal] = []

        for scheduled, result in zip(spec.periods, report.periods, strict=True):
            if (
                result.period_id != scheduled.period_id
                or result.decision_at != scheduled.decision_at
                or result.fill_at != scheduled.fill_at
            ):
                return False
            expected_actions = tuple(
                action
                for action in sorted(
                    spec.corporate_actions,
                    key=lambda item: (item.effective_at, item.instrument_id),
                )
                if action.effective_at <= scheduled.decision_at
                and action.available_at <= scheduled.decision_at
                and digest_canonical(action) not in applied
            )
            if result.applied_actions != expected_actions:
                return False
            for action in expected_actions:
                identity = (action.instrument_id, action.instrument_version)
                if identity in terminally_delisted:
                    return False
                applied.add(digest_canonical(action))
                quantity = quantities.get(action.instrument_id, Decimal(0))
                if quantity > 0 and versions.get(action.instrument_id) != action.instrument_version:
                    return False
                if action.kind == CorporateActionKind.SPLIT:
                    if action.split_ratio is None:
                        return False
                    quantities[action.instrument_id] = quantity * action.split_ratio
                else:
                    if action.cash_per_share is None:
                        return False
                    cash += quantity * action.cash_per_share
                if action.kind == CorporateActionKind.DELISTING_CASH:
                    quantities.pop(action.instrument_id, None)
                    versions.pop(action.instrument_id, None)
                    terminally_delisted.add(identity)

            fills_by_id = {item.client_order_id: item for item in result.fills}
            if len(fills_by_id) != len(result.fills):
                return False
            classified = (
                set(fills_by_id)
                | set(result.unfilled_order_ids)
                | set(result.stale_rejected_order_ids)
            )
            if classified != {item.client_order_id for item in scheduled.orders} or len(
                classified
            ) != len(result.fills) + len(result.unfilled_order_ids) + len(
                result.stale_rejected_order_ids
            ):
                return False
            for order in scheduled.orders:
                if (order.instrument_id, order.instrument_version) in terminally_delisted:
                    return False
                try:
                    current = _latest_bar(
                        spec.bars,
                        order.instrument_id,
                        scheduled.decision_at,
                        order.instrument_version,
                    )
                    is_stale = _stale(current, scheduled.decision_at, spec.max_bar_age_seconds)
                except ValueError:
                    is_stale = True
                if is_stale:
                    if order.client_order_id not in result.stale_rejected_order_ids:
                        return False
                    continue
                bar = next_market_bar(
                    spec.bars, instrument_id=order.instrument_id, after=scheduled.decision_at
                )
                if (
                    bar.tradable_at != scheduled.fill_at
                    or bar.instrument_version != order.instrument_version
                ):
                    return False
                if not _limit_allows(order, bar.open_price):
                    if order.client_order_id not in result.unfilled_order_ids:
                        return False
                    continue
                cost = order.quantity * bar.open_price * spec.transaction_cost_rate
                expected_fill = PaperFill(
                    client_order_id=order.client_order_id,
                    instrument_id=order.instrument_id,
                    instrument_version=order.instrument_version,
                    side=order.side,
                    quantity=order.quantity,
                    price=bar.open_price,
                    transaction_cost=cost,
                    filled_at=bar.tradable_at,
                    market_data_digest=digest_canonical(bar),
                )
                if fills_by_id.get(order.client_order_id) != expected_fill:
                    return False
                notional = expected_fill.quantity * expected_fill.price
                held = quantities.get(expected_fill.instrument_id, Decimal(0))
                if held > 0 and versions.get(expected_fill.instrument_id) != (
                    expected_fill.instrument_version
                ):
                    return False
                if expected_fill.side == OrderSide.BUY:
                    cash -= notional + expected_fill.transaction_cost
                    quantities[expected_fill.instrument_id] = held + expected_fill.quantity
                else:
                    if held < expected_fill.quantity:
                        return False
                    cash += notional - expected_fill.transaction_cost
                    quantities[expected_fill.instrument_id] = held - expected_fill.quantity
                if cash < 0:
                    return False
                versions[expected_fill.instrument_id] = expected_fill.instrument_version

            quantities = {key: value for key, value in quantities.items() if value > 0}
            versions = {key: value for key, value in versions.items() if key in quantities}
            marks: dict[str, Decimal] = {}
            positions: list[PositionLedgerEntry] = []
            for instrument_id, quantity in sorted(quantities.items()):
                if quantity <= 0:
                    continue
                bar = _latest_bar(
                    spec.bars,
                    instrument_id,
                    scheduled.fill_at,
                    versions[instrument_id],
                )
                if _stale(bar, scheduled.fill_at, spec.max_bar_age_seconds):
                    return False
                marks[instrument_id] = bar.close_price
                positions.append(
                    PositionLedgerEntry(
                        instrument_id=instrument_id,
                        instrument_version=versions[instrument_id],
                        quantity=quantity,
                        mark_price=bar.close_price,
                        marked_at=scheduled.fill_at,
                        source_digest=digest_canonical(bar),
                    )
                )
            nav = marked_nav(cash, quantities, marks)
            strategy_return = nav / previous_nav - Decimal(1)
            benchmark_bar = _latest_bar(spec.bars, spec.benchmark_instrument_id, scheduled.fill_at)
            if _stale(benchmark_bar, scheduled.fill_at, spec.max_bar_age_seconds):
                return False
            benchmark_mark = benchmark_bar.close_price
            benchmark_return = benchmark_mark / previous_benchmark - Decimal(1)
            if (
                result.cash != cash
                or result.positions != tuple(positions)
                or result.nav != nav
                or result.period_return != strategy_return
                or result.benchmark_return != benchmark_return
            ):
                return False
            strategy_returns.append(strategy_return)
            benchmark_returns.append(benchmark_return)
            previous_nav = nav
            previous_benchmark = benchmark_mark

        returns = tuple(strategy_returns)
        windows = walk_forward_windows(
            len(spec.periods),
            training_observations=spec.walk_forward_training_periods,
            test_observations=spec.walk_forward_test_periods,
            step=spec.walk_forward_step,
        )
        holdout_ids = set(spec.holdout_period_ids)
        expected_holdout_returns = tuple(
            item.period_return for item in report.periods if item.period_id in holdout_ids
        )
        expected_placebo_returns = (Decimal(0),) * len(returns)
        expected_performance = performance_report(
            returns,
            annualization_periods=spec.annualization_periods,
            strategy_trials=spec.strategy_trials,
            out_of_sample_fold_returns=tuple(
                returns[test_start:test_end] for _, _, test_start, test_end in windows
            ),
            holdout_returns=expected_holdout_returns,
            benchmark_returns=tuple(benchmark_returns),
            placebo_returns=expected_placebo_returns,
        )
        return (
            report.final_cash == cash
            and report.final_positions == report.periods[-1].positions
            and report.final_nav == previous_nav
            and report.benchmark_return == previous_benchmark / initial_benchmark - Decimal(1)
            and report.strategy_returns == returns
            and report.benchmark_returns == tuple(benchmark_returns)
            and report.walk_forward_windows == windows
            and report.holdout_returns == expected_holdout_returns
            and report.placebo_returns == expected_placebo_returns
            and report.performance == expected_performance
        )
    except (KeyError, ValueError):
        return False
