from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegisquant.contracts.risk import (
    DecisionOutcome,
    OrderBundle,
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecisionPayload,
    RuleResult,
    RuleStatus,
    TimeInForce,
    TradingEnvironment,
)
from aegisquant.security.digests import digest_canonical
from aegisquant.security.risk_signing import (
    ExecutionAuthorizationGate,
    InMemoryDecisionConsumptionStore,
    RiskDecisionSigner,
    RiskDecisionVerifier,
    RiskVerificationContext,
    RiskVerificationError,
    TrustedRiskKey,
)

D = "sha256:" + "a" * 64


def make_bundle(quantity: str = "10") -> OrderBundle:
    return OrderBundle(
        tenant_id="tenant-a",
        environment=TradingEnvironment.PAPER,
        legal_entity_id="entity-a",
        account_id="paper-account-1",
        broker_id="simulator",
        strategy_id="control-strategy",
        case_id=uuid4(),
        request_id=uuid4(),
        portfolio_state_sequence=7,
        orders=(
            OrderIntent(
                client_order_id="aq-order-1",
                instrument_id="SPY",
                instrument_version="security-master-1",
                venue_id="ARCX",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
                quantity=quantity,
                limit_price="500.25",
                currency="USD",
            ),
        ),
    )


def make_payload(bundle: OrderBundle, now: datetime) -> RiskDecisionPayload:
    bundle_digest = digest_canonical(bundle)
    return RiskDecisionPayload(
        tenant_id=bundle.tenant_id,
        decision_id=uuid4(),
        request_id=bundle.request_id,
        case_id=bundle.case_id,
        issuance_sequence=1,
        nonce="ab" * 16,
        environment=bundle.environment,
        legal_entity_id=bundle.legal_entity_id,
        account_id=bundle.account_id,
        broker_id=bundle.broker_id,
        strategy_id=bundle.strategy_id,
        outcome=DecisionOutcome.APPROVE,
        policy_bundle_digest=D,
        policy_epoch=3,
        kill_switch_epoch=2,
        input_manifest_digest=D,
        portfolio_state_sequence=bundle.portfolio_state_sequence,
        portfolio_snapshot_digest=D,
        open_orders_snapshot_digest=D,
        market_data_snapshot_digest=D,
        reference_data_snapshot_digest=D,
        fx_snapshot_digest=D,
        model_validation_manifest_digest=D,
        requested_order_bundle_digest=bundle_digest,
        approved_order_bundle_digest=bundle_digest,
        rule_results=(
            RuleResult(
                rule_id="max-order-notional",
                rule_version="1",
                status=RuleStatus.PASS,
                reason_code="WITHIN_LIMIT",
            ),
        ),
        created_at=now,
        not_before=now,
        expires_at=now + timedelta(seconds=30),
    )


def context(bundle: OrderBundle) -> RiskVerificationContext:
    return RiskVerificationContext(
        tenant_id=bundle.tenant_id,
        environment=str(bundle.environment),
        legal_entity_id=bundle.legal_entity_id,
        account_id=bundle.account_id,
        broker_id=bundle.broker_id,
        strategy_id=bundle.strategy_id,
        policy_epoch=3,
        kill_switch_epoch=2,
        portfolio_state_sequence=bundle.portfolio_state_sequence,
        input_manifest_digest=D,
        portfolio_snapshot_digest=D,
        open_orders_snapshot_digest=D,
        market_data_snapshot_digest=D,
        reference_data_snapshot_digest=D,
        fx_snapshot_digest=D,
        model_validation_manifest_digest=D,
    )


def trusted_key(private_key: Ed25519PrivateKey, now: datetime) -> TrustedRiskKey:
    return TrustedRiskKey(
        public_key=private_key.public_key(),
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
    )


def test_signed_decision_binds_exact_order_bundle_and_is_single_use() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    bundle = make_bundle()
    private_key = Ed25519PrivateKey.generate()
    signed = RiskDecisionSigner("risk-key-1", private_key).sign(make_payload(bundle, now))
    verifier = RiskDecisionVerifier({"risk-key-1": trusted_key(private_key, now)})
    gate = ExecutionAuthorizationGate(verifier, InMemoryDecisionConsumptionStore())
    gate.authorize_once(signed, bundle, context(bundle), now=now)
    with pytest.raises(RiskVerificationError, match="already been consumed"):
        gate.authorize_once(signed, bundle, context(bundle), now=now)


def test_mutated_order_is_rejected_even_with_valid_decision_signature() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    bundle = make_bundle()
    private_key = Ed25519PrivateKey.generate()
    signed = RiskDecisionSigner("risk-key-1", private_key).sign(make_payload(bundle, now))
    mutated_data = bundle.model_dump(mode="python")
    mutated_order = bundle.orders[0].model_dump(mode="python")
    mutated_order["quantity"] = "11"
    mutated_data["orders"] = (mutated_order,)
    mutated = OrderBundle.model_validate(mutated_data)
    verifier = RiskDecisionVerifier({"risk-key-1": trusted_key(private_key, now)})
    with pytest.raises(RiskVerificationError, match="digest"):
        verifier.verify(signed, mutated, context(bundle), now=now)


def test_expiry_is_exclusive() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    bundle = make_bundle()
    private_key = Ed25519PrivateKey.generate()
    signed = RiskDecisionSigner("risk-key-1", private_key).sign(make_payload(bundle, now))
    verifier = RiskDecisionVerifier({"risk-key-1": trusted_key(private_key, now)})
    with pytest.raises(RiskVerificationError, match="validity window"):
        verifier.verify(signed, bundle, context(bundle), now=now + timedelta(seconds=30))


def test_revoked_key_is_rejected() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    bundle = make_bundle()
    private_key = Ed25519PrivateKey.generate()
    signed = RiskDecisionSigner("risk-key-1", private_key).sign(make_payload(bundle, now))
    revoked = TrustedRiskKey(
        public_key=private_key.public_key(),
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
        revoked_at=now,
    )
    verifier = RiskDecisionVerifier({"risk-key-1": revoked})
    with pytest.raises(RiskVerificationError, match="revoked"):
        verifier.verify(signed, bundle, context(bundle), now=now)


def test_changed_open_order_snapshot_is_rejected() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    bundle = make_bundle()
    private_key = Ed25519PrivateKey.generate()
    signed = RiskDecisionSigner("risk-key-1", private_key).sign(make_payload(bundle, now))
    verifier = RiskDecisionVerifier({"risk-key-1": trusted_key(private_key, now)})
    stale_context = context(bundle)
    stale_context = RiskVerificationContext(
        **{
            **stale_context.__dict__,
            "open_orders_snapshot_digest": "sha256:" + "b" * 64,
        }
    )
    with pytest.raises(RiskVerificationError, match="stale or mismatched"):
        verifier.verify(signed, bundle, stale_context, now=now)
