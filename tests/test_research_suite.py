from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from aegisquant.contracts.learning import LearningCandidate, LearningProposalManifest
from aegisquant.contracts.research import (
    CorporateAction,
    CorporateActionKind,
    MarketBar,
    PositionLedgerEntry,
    SecurityVersion,
)
from aegisquant.contracts.risk import (
    DecisionOutcome,
    OrderBundle,
    OrderIntent,
    OrderSide,
    OrderType,
    ProtectedHeader,
    RiskDecisionPayload,
    SignedRiskDecision,
    TimeInForce,
    TradingEnvironment,
)
from aegisquant.learning.governance import approve_candidate_v2, evaluate_candidate_v2
from aegisquant.quant.metrics import (
    performance_report,
    placebo_returns,
    stationary_block_bootstrap_indices,
    walk_forward_windows,
)
from aegisquant.quant.paper import (
    DeterministicPaperVenue,
    PaperAccountState,
    PaperExecutionError,
    reconcile_execution,
)
from aegisquant.quant.pit import apply_available_corporate_actions, available_bars, marked_nav
from aegisquant.quant.portfolio import (
    Forecast,
    PortfolioPolicy,
    blend_forecasts,
    build_long_only_target,
    propose_long_only,
)
from aegisquant.quant.risk import RiskPolicy, evaluate_policy, policy_allows
from aegisquant.quant.timeline import ExecutionTimeline
from aegisquant.security.digests import digest_canonical
from aegisquant.security.risk_signing import (
    ExecutionAuthorizationGate,
    RiskVerificationContext,
    RiskVerificationError,
)

DIGEST = "sha256:" + "c" * 64


def bar(
    *, instrument_id: str = "AAA", observed_at: datetime, tradable_at: datetime, close: str = "100"
) -> MarketBar:
    return MarketBar(
        instrument_id=instrument_id,
        instrument_version="sec-v1",
        observed_at=observed_at,
        available_at=observed_at,
        tradable_at=tradable_at,
        open_price=close,
        close_price=close,
        volume="100000",
        currency="USD",
    )


def security(instrument_id: str = "AAA") -> SecurityVersion:
    return SecurityVersion(
        instrument_id=instrument_id,
        instrument_version="sec-v1",
        sector_id="technology",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
    )


def bundle(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: str = "10",
    case_id: UUID | None = None,
) -> OrderBundle:
    return OrderBundle(
        tenant_id="tenant-a",
        environment=TradingEnvironment.PAPER,
        legal_entity_id="entity-a",
        account_id="paper-1",
        broker_id="simulator",
        strategy_id="multi-asset-control",
        case_id=case_id or uuid4(),
        request_id=uuid4(),
        portfolio_state_sequence=0,
        orders=(
            OrderIntent(
                client_order_id="order-1",
                instrument_id="AAA",
                instrument_version="sec-v1",
                venue_id="fixture-venue",
                side=side,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                quantity=quantity,
                currency="USD",
            ),
        ),
    )


def paper_venue() -> tuple[DeterministicPaperVenue, Mock]:
    gate = Mock(spec=ExecutionAuthorizationGate)
    return DeterministicPaperVenue(authorization_gate=gate), gate


def authorization_inputs(
    order_bundle: OrderBundle,
    account: PaperAccountState,
    bars: tuple[MarketBar, ...],
    securities: dict[str, SecurityVersion],
    policy: RiskPolicy,
    timeline: ExecutionTimeline,
) -> tuple[SignedRiskDecision, RiskVerificationContext]:
    required = {order.instrument_id for order in order_bundle.orders} | {
        position.instrument_id for position in account.positions
    }
    current = {
        instrument_id: max(
            (
                item
                for item in bars
                if item.instrument_id == instrument_id
                and item.available_at <= timeline.order_submitted_at
            ),
            key=lambda item: (item.available_at, item.observed_at),
        )
        for instrument_id in required
    }
    context = RiskVerificationContext(
        tenant_id=order_bundle.tenant_id,
        environment=str(order_bundle.environment),
        legal_entity_id=order_bundle.legal_entity_id,
        account_id=order_bundle.account_id,
        broker_id=order_bundle.broker_id,
        strategy_id=order_bundle.strategy_id,
        policy_epoch=1,
        kill_switch_epoch=0,
        portfolio_state_sequence=order_bundle.portfolio_state_sequence,
        input_manifest_digest=DIGEST,
        portfolio_snapshot_digest=digest_canonical(account),
        open_orders_snapshot_digest=digest_canonical(()),
        market_data_snapshot_digest=digest_canonical(
            tuple(current[item] for item in sorted(current))
        ),
        reference_data_snapshot_digest=digest_canonical(
            tuple(securities[item] for item in sorted(securities))
        ),
        fx_snapshot_digest=digest_canonical({"USD": Decimal(1)}),
        model_validation_manifest_digest=DIGEST,
    )
    payload = RiskDecisionPayload(
        tenant_id=order_bundle.tenant_id,
        decision_id=uuid4(),
        request_id=order_bundle.request_id,
        case_id=order_bundle.case_id,
        issuance_sequence=1,
        nonce="ab" * 16,
        environment=order_bundle.environment,
        legal_entity_id=order_bundle.legal_entity_id,
        account_id=order_bundle.account_id,
        broker_id=order_bundle.broker_id,
        strategy_id=order_bundle.strategy_id,
        outcome=DecisionOutcome.APPROVE,
        policy_bundle_digest=digest_canonical(policy),
        policy_epoch=context.policy_epoch,
        kill_switch_epoch=context.kill_switch_epoch,
        input_manifest_digest=context.input_manifest_digest,
        portfolio_state_sequence=context.portfolio_state_sequence,
        portfolio_snapshot_digest=context.portfolio_snapshot_digest,
        open_orders_snapshot_digest=context.open_orders_snapshot_digest,
        market_data_snapshot_digest=context.market_data_snapshot_digest,
        reference_data_snapshot_digest=context.reference_data_snapshot_digest,
        fx_snapshot_digest=context.fx_snapshot_digest,
        model_validation_manifest_digest=context.model_validation_manifest_digest,
        execution_plan_digest=digest_canonical(
            {
                "bars": bars,
                "timeline": timeline,
                "transaction_cost_rate": Decimal("0.0005"),
            }
        ),
        requested_order_bundle_digest=digest_canonical(order_bundle),
        approved_order_bundle_digest=digest_canonical(order_bundle),
        rule_results=(),
        created_at=timeline.decision_at,
        not_before=timeline.order_submitted_at,
        expires_at=timeline.order_submitted_at + timedelta(minutes=5),
    )
    return (
        SignedRiskDecision(
            protected=ProtectedHeader(key_id="fixture-key"),
            payload=payload,
            signature_b64url="a" * 86,
        ),
        context,
    )


def test_long_only_target_preserves_cash_and_rejects_duplicate_forecasts() -> None:
    forecast = Forecast(
        instrument_id="AAA",
        horizon_days=20,
        expected_return="0.10",
        probability_positive="0.60",
        confidence="0.80",
        uncertainty="0.20",
        feature_provenance=("fixture-v1",),
    )
    blended = blend_forecasts((forecast,), uncertainty_floor=Decimal("0.01"))
    target = build_long_only_target(
        (blended,), policy=PortfolioPolicy(maximum_position_weight="0.20")
    )
    assert target.weights[0].weight == Decimal("0.20")
    assert target.cash_weight == Decimal("0.80")
    with pytest.raises(ValueError, match="one blended forecast"):
        propose_long_only((blended, blended), policy=PortfolioPolicy())


def test_pit_filters_future_data_and_corporate_actions() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    visible = bar(observed_at=now, tradable_at=now + timedelta(days=1))
    future = bar(observed_at=now + timedelta(days=1), tradable_at=now + timedelta(days=2))
    assert available_bars((visible, future), information_cutoff=now) == (visible,)
    action = CorporateAction(
        instrument_id="AAA",
        instrument_version="sec-v1",
        kind=CorporateActionKind.CASH_DIVIDEND,
        effective_at=now,
        available_at=now + timedelta(days=1),
        cash_per_share="1.25",
    )
    assert apply_available_corporate_actions(
        {"AAA": Decimal("10")}, Decimal("1"), (action,), as_of=now
    )[1] == Decimal("1")
    assert apply_available_corporate_actions(
        {"AAA": Decimal("10")}, Decimal("1"), (action,), as_of=now + timedelta(days=1)
    )[1] == Decimal("13.50")


def test_policy_and_paper_venue_reject_short_and_enforce_next_bar_fill() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    current = bar(observed_at=now - timedelta(minutes=1), tradable_at=now)
    known_ahead = bar(observed_at=now - timedelta(seconds=30), tradable_at=now + timedelta(hours=1))
    next_bar = bar(
        observed_at=now + timedelta(hours=1),
        tradable_at=now + timedelta(days=1),
        close="101",
    )
    held_bar = bar(
        instrument_id="BBB",
        observed_at=now - timedelta(minutes=1),
        tradable_at=now,
        close="50",
    )
    held_next_bar = bar(
        instrument_id="BBB",
        observed_at=now + timedelta(hours=1),
        tradable_at=now + timedelta(days=1),
        close="51",
    )
    policy = RiskPolicy(
        policy_id="paper-v1",
        policy_version="1",
        maximum_position_weight="0.50",
        maximum_sector_weight="1",
        maximum_turnover="1",
    )
    case_id = uuid4()
    order_bundle = bundle(case_id=case_id)
    account = PaperAccountState(
        tenant_id=order_bundle.tenant_id,
        case_id=order_bundle.case_id,
        account_id=order_bundle.account_id,
        cash="10000",
        positions=(
            PositionLedgerEntry(
                instrument_id="BBB",
                instrument_version="sec-v1",
                quantity="1",
                mark_price="49",
                marked_at=now,
                source_digest=DIGEST,
            ),
        ),
        state_sequence=0,
    )
    timeline = ExecutionTimeline(
        information_cutoff=now - timedelta(seconds=1),
        decision_at=now,
        order_submitted_at=now,
        fill_at=now + timedelta(days=1),
    )
    venue, gate = paper_venue()
    test_bars = (current, known_ahead, next_bar, held_bar, held_next_bar)
    test_securities = {"AAA": security(), "BBB": security("BBB")}
    signed_decision, verification_context = authorization_inputs(
        order_bundle, account, test_bars, test_securities, policy, timeline
    )
    result = venue.execute(
        order_bundle,
        signed_decision=signed_decision,
        verification_context=verification_context,
        account=account,
        bars=test_bars,
        securities=test_securities,
        policy=policy,
        timeline=timeline,
        as_of=now,
    )
    assert result.fills[0].filled_at == next_bar.tradable_at
    assert {position.instrument_id: position.quantity for position in result.account.positions} == {
        "AAA": Decimal("10"),
        "BBB": Decimal("1"),
    }
    assert next(
        position for position in result.account.positions if position.instrument_id == "BBB"
    ).mark_price == Decimal("51")
    assert (
        next(
            position for position in result.account.positions if position.instrument_id == "AAA"
        ).marked_at
        == timeline.fill_at
    )
    gate.authorize_once.assert_called_once_with(
        signed_decision,
        order_bundle,
        verification_context,
        now=timeline.order_submitted_at,
        human_approval=None,
    )
    assert reconcile_execution(account, result)
    short_results = evaluate_policy(
        bundle(side=OrderSide.SELL, case_id=case_id),
        positions=(),
        bars={"AAA": current},
        securities={"AAA": security()},
        cash=Decimal("10000"),
        policy=policy,
        as_of=now,
    )
    assert not policy_allows(short_results)
    with pytest.raises(PaperExecutionError, match="pre-trade"):
        venue.execute(
            bundle(side=OrderSide.SELL, case_id=case_id),
            signed_decision=signed_decision,
            verification_context=verification_context,
            account=account,
            bars=test_bars,
            securities=test_securities,
            policy=policy,
            timeline=timeline,
            as_of=now,
        )


def test_paper_account_requires_tenant_case_and_account_identity() -> None:
    with pytest.raises(ValidationError):
        PaperAccountState(cash="10000", positions=(), state_sequence=0)


def test_risk_rejects_future_market_data_and_records_correct_units() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    future = bar(observed_at=now + timedelta(seconds=1), tradable_at=now + timedelta(days=1))
    results = evaluate_policy(
        bundle(),
        positions=(),
        bars={"AAA": future},
        securities={"AAA": security()},
        cash=Decimal("10000"),
        policy=RiskPolicy(
            policy_id="paper-v1",
            policy_version="1",
            maximum_position_weight="1",
            maximum_sector_weight="1",
            maximum_turnover="1",
        ),
        as_of=now,
    )
    assert not policy_allows(results)
    assert {result.rule_id: result.unit for result in results} == {
        "market-data-staleness": "SECONDS",
        "maximum-order-notional": "USD",
        "long-only": "SHARES",
        "maximum-turnover": "RATIO",
        "maximum-gross-exposure": "RATIO",
        "maximum-position-weight": "RATIO",
        "maximum-sector-weight": "RATIO",
    }
    with pytest.raises(ValueError, match="instrument identity"):
        evaluate_policy(
            bundle(),
            positions=(),
            bars={"AAA": future.model_copy(update={"instrument_id": "BBB"})},
            securities={"AAA": security()},
            cash=Decimal("10000"),
            policy=RiskPolicy(policy_id="paper-v1", policy_version="1"),
            as_of=now,
        )


@pytest.mark.parametrize("tamper", ["reference", "mark_time"])
def test_risk_rejects_substituted_position_identity_and_future_marks(tamper: str) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    position = PositionLedgerEntry(
        instrument_id="AAA",
        instrument_version="sec-v1",
        quantity="1",
        mark_price="100",
        marked_at=now,
        source_digest=DIGEST,
    )
    reference = security()
    if tamper == "reference":
        reference = reference.model_copy(update={"instrument_id": "BBB"})
    else:
        position = position.model_copy(update={"marked_at": now + timedelta(seconds=1)})
    current = bar(observed_at=now - timedelta(seconds=1), tradable_at=now)
    with pytest.raises(ValueError, match="position"):
        evaluate_policy(
            bundle(),
            positions=(position,),
            bars={"AAA": current},
            securities={"AAA": reference},
            cash=Decimal("10000"),
            policy=RiskPolicy(policy_id="paper-v1", policy_version="1"),
            as_of=now,
            include_orders=False,
        )


def test_risk_values_positions_at_current_bound_bar_and_rejects_stale_marks() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    position = PositionLedgerEntry(
        instrument_id="AAA",
        instrument_version="sec-v1",
        quantity="1",
        mark_price="1",
        marked_at=now - timedelta(seconds=1),
        source_digest=DIGEST,
    )
    current = bar(
        observed_at=now - timedelta(seconds=1),
        tradable_at=now,
        close="200",
    )
    policy = RiskPolicy(
        policy_id="paper-v1",
        policy_version="1",
        maximum_position_weight="0.50",
        maximum_sector_weight="1",
        maximum_turnover="1",
    )

    results = evaluate_policy(
        bundle(),
        positions=(position,),
        bars={"AAA": current},
        securities={"AAA": security()},
        cash=Decimal("100"),
        policy=policy,
        as_of=now,
        include_orders=False,
    )
    assert next(result for result in results if result.rule_id == "maximum-position-weight") == (
        next(result for result in results if result.reason_code == "EXCEEDED")
    )

    stale = current.model_copy(
        update={"observed_at": now - timedelta(days=2), "available_at": now - timedelta(days=2)}
    )
    with pytest.raises(ValueError, match="current market bar"):
        evaluate_policy(
            bundle(),
            positions=(position,),
            bars={"AAA": stale},
            securities={"AAA": security()},
            cash=Decimal("100"),
            policy=policy,
            as_of=now,
            include_orders=False,
        )


def test_paper_venue_rejects_timeline_and_security_version_mismatches() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    current = bar(observed_at=now - timedelta(minutes=1), tradable_at=now)
    next_bar = bar(observed_at=now + timedelta(hours=1), tradable_at=now + timedelta(days=1))
    order_bundle = bundle()
    account = PaperAccountState(
        tenant_id=order_bundle.tenant_id,
        case_id=order_bundle.case_id,
        account_id=order_bundle.account_id,
        cash="10000",
        positions=(),
        state_sequence=0,
    )
    policy = RiskPolicy(
        policy_id="paper-v1",
        policy_version="1",
        maximum_position_weight="1",
        maximum_sector_weight="1",
        maximum_turnover="1",
    )
    timeline = ExecutionTimeline(
        information_cutoff=now - timedelta(seconds=1),
        decision_at=now,
        order_submitted_at=now,
        fill_at=now + timedelta(days=2),
    )
    venue, _ = paper_venue()
    signed_decision, verification_context = authorization_inputs(
        order_bundle, account, (current, next_bar), {"AAA": security()}, policy, timeline
    )
    with pytest.raises(PaperExecutionError, match="execution timeline"):
        venue.execute(
            order_bundle,
            signed_decision=signed_decision,
            verification_context=verification_context,
            account=account,
            bars=(current, next_bar),
            securities={"AAA": security()},
            policy=policy,
            timeline=timeline,
            as_of=now,
        )
    mismatched_security = security().model_copy(update={"instrument_version": "sec-v2"})
    with pytest.raises(ValueError, match="security version"):
        evaluate_policy(
            bundle(),
            positions=(),
            bars={"AAA": current},
            securities={"AAA": mismatched_security},
            cash=Decimal("10000"),
            policy=policy,
            as_of=now,
        )


def test_paper_venue_fails_closed_when_execution_authorization_is_denied() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    current = bar(observed_at=now - timedelta(minutes=1), tradable_at=now)
    next_bar = bar(observed_at=now + timedelta(hours=1), tradable_at=now + timedelta(days=1))
    timeline = ExecutionTimeline(
        information_cutoff=now - timedelta(seconds=1),
        decision_at=now,
        order_submitted_at=now,
        fill_at=now + timedelta(days=1),
    )
    venue, gate = paper_venue()
    gate.authorize_once.side_effect = RiskVerificationError("invalid risk signature")
    order_bundle = bundle()
    account = PaperAccountState(
        tenant_id=order_bundle.tenant_id,
        case_id=order_bundle.case_id,
        account_id=order_bundle.account_id,
        cash="10000",
        positions=(),
        state_sequence=0,
    )
    policy = RiskPolicy(
        policy_id="paper-v1",
        policy_version="1",
        maximum_position_weight="1",
        maximum_sector_weight="1",
        maximum_turnover="1",
    )
    signed_decision, verification_context = authorization_inputs(
        order_bundle, account, (current, next_bar), {"AAA": security()}, policy, timeline
    )
    with pytest.raises(RiskVerificationError, match="invalid risk signature"):
        venue.execute(
            order_bundle,
            signed_decision=signed_decision,
            verification_context=verification_context,
            account=account,
            bars=(current, next_bar),
            securities={"AAA": security()},
            policy=policy,
            timeline=timeline,
            as_of=now,
        )


@pytest.mark.parametrize("tamper", ["account", "market", "reference", "policy", "timeline"])
def test_paper_venue_rejects_inputs_not_bound_to_signed_decision(tamper: str) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    current = bar(observed_at=now - timedelta(minutes=1), tradable_at=now)
    next_bar = bar(observed_at=now + timedelta(hours=1), tradable_at=now + timedelta(days=1))
    bars = (current, next_bar)
    order_bundle = bundle()
    account = PaperAccountState(
        tenant_id=order_bundle.tenant_id,
        case_id=order_bundle.case_id,
        account_id=order_bundle.account_id,
        cash="10000",
        positions=(),
        state_sequence=0,
    )
    securities = {"AAA": security()}
    policy = RiskPolicy(
        policy_id="paper-v1",
        policy_version="1",
        maximum_position_weight="1",
        maximum_sector_weight="1",
        maximum_turnover="1",
    )
    timeline = ExecutionTimeline(
        information_cutoff=now - timedelta(seconds=1),
        decision_at=now,
        order_submitted_at=now,
        fill_at=now + timedelta(days=1),
    )
    signed, context = authorization_inputs(
        order_bundle, account, bars, securities, policy, timeline
    )
    if tamper == "account":
        account = account.model_copy(update={"cash": Decimal("9999")})
    elif tamper == "market":
        bars = (current.model_copy(update={"close_price": Decimal("99")}), next_bar)
    elif tamper == "reference":
        securities = {"AAA": security().model_copy(update={"sector_id": "substituted"})}
    elif tamper == "policy":
        policy = policy.model_copy(update={"maximum_order_notional": Decimal("9999")})
    else:
        timeline = timeline.model_copy(update={"order_submitted_at": now + timedelta(seconds=1)})
    venue, _ = paper_venue()
    with pytest.raises(PaperExecutionError, match="signed decision"):
        venue.execute(
            order_bundle,
            signed_decision=signed,
            verification_context=context,
            account=account,
            bars=bars,
            securities=securities,
            policy=policy,
            timeline=timeline,
            as_of=now,
        )


@pytest.mark.parametrize("tamper", ["future_bar", "fill_at", "cost"])
def test_paper_venue_binds_future_bars_full_timeline_and_cost(tamper: str) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    current = bar(observed_at=now - timedelta(minutes=1), tradable_at=now)
    next_bar = bar(observed_at=now + timedelta(hours=1), tradable_at=now + timedelta(days=1))
    bars = (current, next_bar)
    order_bundle = bundle()
    account = PaperAccountState(
        tenant_id=order_bundle.tenant_id,
        case_id=order_bundle.case_id,
        account_id=order_bundle.account_id,
        cash="10000",
        positions=(),
        state_sequence=0,
    )
    securities = {"AAA": security()}
    policy = RiskPolicy(
        policy_id="paper-v1",
        policy_version="1",
        maximum_position_weight="1",
        maximum_sector_weight="1",
        maximum_turnover="1",
    )
    timeline = ExecutionTimeline(
        information_cutoff=now - timedelta(seconds=1),
        decision_at=now,
        order_submitted_at=now,
        fill_at=now + timedelta(days=1),
    )
    signed, context = authorization_inputs(
        order_bundle, account, bars, securities, policy, timeline
    )
    assert hasattr(signed.payload, "execution_plan_digest")
    venue, gate = paper_venue()
    if tamper == "future_bar":
        bars = (current, next_bar.model_copy(update={"open_price": Decimal("99")}))
    elif tamper == "fill_at":
        timeline = timeline.model_copy(update={"fill_at": now + timedelta(days=2)})
    else:
        venue = DeterministicPaperVenue(
            authorization_gate=gate,
            transaction_cost_rate=Decimal("0.001"),
        )
    with pytest.raises(PaperExecutionError, match="signed execution plan"):
        venue.execute(
            order_bundle,
            signed_decision=signed,
            verification_context=context,
            account=account,
            bars=bars,
            securities=securities,
            policy=policy,
            timeline=timeline,
            as_of=now,
        )


def test_paper_venue_rejects_fill_bar_version_and_expired_security() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    current = bar(observed_at=now - timedelta(minutes=1), tradable_at=now)
    next_bar = bar(observed_at=now + timedelta(hours=1), tradable_at=now + timedelta(days=1))
    order_bundle = bundle()
    account = PaperAccountState(
        tenant_id=order_bundle.tenant_id,
        case_id=order_bundle.case_id,
        account_id=order_bundle.account_id,
        cash="10000",
        positions=(),
        state_sequence=0,
    )
    policy = RiskPolicy(
        policy_id="paper-v1",
        policy_version="1",
        maximum_position_weight="1",
        maximum_sector_weight="1",
        maximum_turnover="1",
    )
    timeline = ExecutionTimeline(
        information_cutoff=now - timedelta(seconds=1),
        decision_at=now,
        order_submitted_at=now,
        fill_at=now + timedelta(days=1),
    )
    active = security()
    venue, _ = paper_venue()
    mismatched_bars = (
        current,
        next_bar.model_copy(update={"instrument_version": "sec-v2"}),
    )
    signed, context = authorization_inputs(
        order_bundle, account, mismatched_bars, {"AAA": active}, policy, timeline
    )
    with pytest.raises(PaperExecutionError, match="fill bar version"):
        venue.execute(
            order_bundle,
            signed_decision=signed,
            verification_context=context,
            account=account,
            bars=mismatched_bars,
            securities={"AAA": active},
            policy=policy,
            timeline=timeline,
            as_of=now,
        )
    expired = active.model_copy(update={"valid_until": timeline.fill_at})
    signed, context = authorization_inputs(
        order_bundle, account, (current, next_bar), {"AAA": expired}, policy, timeline
    )
    with pytest.raises(PaperExecutionError, match="active security"):
        venue.execute(
            order_bundle,
            signed_decision=signed,
            verification_context=context,
            account=account,
            bars=(current, next_bar),
            securities={"AAA": expired},
            policy=policy,
            timeline=timeline,
            as_of=now,
        )


def test_metrics_are_deterministic_and_underpowered_results_are_not_overclaimed() -> None:
    report = performance_report((Decimal("0.01"), Decimal("-0.01")), annualization_periods=252)
    assert not report.sufficient_evidence
    assert report.sortino_ratio is None
    three_observations = performance_report(
        (Decimal("0.01"), Decimal("-0.01"), Decimal("0.02")),
        annualization_periods=252,
    )
    assert not three_observations.sufficient_evidence
    assert three_observations.probabilistic_sharpe_ratio is None
    assert three_observations.deflated_sharpe_ratio is None
    with pytest.raises(ValueError, match="step"):
        walk_forward_windows(
            10,
            training_observations=4,
            test_observations=2,
            step=1,
        )
    mature_report = performance_report(
        tuple(Decimal("0.01") if index % 2 else Decimal("-0.005") for index in range(30)),
        annualization_periods=252,
        out_of_sample_fold_returns=((Decimal("-0.01"),), (Decimal("0.01"),)),
    )
    assert mature_report.sufficient_evidence
    assert mature_report.probability_of_backtest_overfitting is None
    assert stationary_block_bootstrap_indices(
        4, block_length=2, seed=7, samples=2
    ) == stationary_block_bootstrap_indices(4, block_length=2, seed=7, samples=2)
    assert marked_nav(Decimal("10"), {"AAA": Decimal("2")}, {"AAA": Decimal("5")}) == Decimal("20")
    assert walk_forward_windows(10, training_observations=4, test_observations=2, step=2) == (
        (0, 4, 4, 6),
        (2, 6, 6, 8),
        (4, 8, 8, 10),
    )
    assert placebo_returns((Decimal("1"), Decimal("2"), Decimal("3")), shift=1) == (
        Decimal("2"),
        Decimal("3"),
        Decimal("1"),
    )


def test_learning_requires_maturity_independent_evaluation_and_manual_approval() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    case_id = uuid4()
    proposal = LearningProposalManifest(
        tenant_id="tenant-a",
        case_id=case_id,
        source_case_id=case_id,
        candidate_id="candidate-1",
        source_actor_id="strategy-owner",
        independent_evaluator_id="independent-review",
        source_outcome_digest=DIGEST,
        baseline_digest=DIGEST,
        proposal_digest=digest_canonical(
            {
                "strategy_parameter": "portfolio_policy.uncertainty_floor",
                "proposed_value": Decimal("0.02"),
            }
        ),
        evaluation_plan_digest=DIGEST,
        rollback_manifest_digest=DIGEST,
        locked_holdout_digest=DIGEST,
        strategy_parameter="portfolio_policy.uncertainty_floor",
        proposed_value="0.02",
        created_at=now,
    )
    candidate = LearningCandidate(
        tenant_id="tenant-a",
        case_id=case_id,
        candidate_id="candidate-1",
        candidate_type="STRATEGY",
        source_manifest_digest=digest_canonical(proposal),
        created_at=now,
        matures_at=now + timedelta(days=20),
    )
    with pytest.raises(ValueError, match="not reached"):
        evaluate_candidate_v2(
            candidate,
            proposal,
            evaluator_id="independent-review",
            evaluation_manifest_digest=DIGEST,
            shadow_passed=True,
            canary_passed=True,
            now=now,
        )
    evaluation = evaluate_candidate_v2(
        candidate,
        proposal,
        evaluator_id="independent-review",
        evaluation_manifest_digest=DIGEST,
        shadow_passed=True,
        canary_passed=True,
        now=candidate.matures_at,
    )
    approval = approve_candidate_v2(
        candidate,
        proposal,
        evaluation,
        approver_id="human-risk-owner",
        approver_is_human=True,
        rollback_manifest_digest=DIGEST,
        now=candidate.matures_at,
        expires_at=candidate.matures_at + timedelta(days=1),
    )
    assert approval.candidate_id == candidate.candidate_id
    future_evaluation = evaluation.model_copy(
        update={"evaluated_at": candidate.matures_at + timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="cannot precede evaluation"):
        approve_candidate_v2(
            candidate,
            proposal,
            future_evaluation,
            approver_id="human-risk-owner",
            approver_is_human=True,
            rollback_manifest_digest=DIGEST,
            now=candidate.matures_at,
            expires_at=candidate.matures_at + timedelta(days=1),
        )
