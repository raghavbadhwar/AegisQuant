"""Ed25519 signing and fail-closed verification for risk decisions."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from aegisquant.contracts.common import canonical_json_bytes, require_utc
from aegisquant.contracts.risk import (
    DecisionOutcome,
    OrderBundle,
    ProtectedHeader,
    RiskDecisionPayload,
    SignedRiskDecision,
)
from aegisquant.security.digests import digest_canonical

DOMAIN_SEPARATOR = b"AEGISQUANT_RISK_DECISION_V1\0"


class RiskVerificationError(ValueError):
    pass


def _signing_bytes(header: ProtectedHeader, payload: RiskDecisionPayload) -> bytes:
    return DOMAIN_SEPARATOR + canonical_json_bytes({"protected": header, "payload": payload})


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class RiskDecisionSigner:
    """Signer for the isolated Hard-Risk boundary.

    Production implementations must replace the in-process private key with a
    KMS/HSM-backed signer. The private key must never enter Execution.
    """

    def __init__(self, key_id: str, private_key: Ed25519PrivateKey) -> None:
        self._key_id = key_id
        self._private_key = private_key

    def sign(self, payload: RiskDecisionPayload) -> SignedRiskDecision:
        header = ProtectedHeader(key_id=self._key_id)
        signature = self._private_key.sign(_signing_bytes(header, payload))
        return SignedRiskDecision(
            protected=header, payload=payload, signature_b64url=_b64url(signature)
        )


@dataclass(frozen=True)
class RiskVerificationContext:
    tenant_id: str
    environment: str
    legal_entity_id: str
    account_id: str
    broker_id: str
    strategy_id: str
    policy_epoch: int
    kill_switch_epoch: int
    portfolio_state_sequence: int
    input_manifest_digest: str
    portfolio_snapshot_digest: str
    open_orders_snapshot_digest: str
    market_data_snapshot_digest: str
    reference_data_snapshot_digest: str
    fx_snapshot_digest: str
    model_validation_manifest_digest: str


@dataclass(frozen=True)
class TrustedRiskKey:
    public_key: Ed25519PublicKey
    valid_from: datetime
    valid_until: datetime
    revoked_at: datetime | None = None


class RiskDecisionVerifier:
    def __init__(self, trusted_keys: dict[str, TrustedRiskKey]) -> None:
        self._trusted_keys = dict(trusted_keys)

    def verify(
        self,
        decision: SignedRiskDecision,
        bundle: OrderBundle,
        context: RiskVerificationContext,
        *,
        now: datetime,
    ) -> RiskDecisionPayload:
        now = require_utc(now)
        trusted_key = self._trusted_keys.get(decision.protected.key_id)
        if trusted_key is None:
            raise RiskVerificationError("untrusted signing key")
        if (
            now < require_utc(trusted_key.valid_from)
            or now >= require_utc(trusted_key.valid_until)
            or (trusted_key.revoked_at is not None and now >= require_utc(trusted_key.revoked_at))
        ):
            raise RiskVerificationError("signing key is inactive or revoked")
        try:
            trusted_key.public_key.verify(
                _b64url_decode(decision.signature_b64url),
                _signing_bytes(decision.protected, decision.payload),
            )
        except (InvalidSignature, ValueError) as exc:
            raise RiskVerificationError("invalid risk signature") from exc
        payload = decision.payload
        if payload.outcome != DecisionOutcome.APPROVE:
            raise RiskVerificationError("decision outcome is not executable")
        if now < payload.not_before or now >= payload.expires_at:
            raise RiskVerificationError("decision is outside its validity window")
        expected = {
            "tenant_id": context.tenant_id,
            "environment": context.environment,
            "legal_entity_id": context.legal_entity_id,
            "account_id": context.account_id,
            "broker_id": context.broker_id,
            "strategy_id": context.strategy_id,
            "policy_epoch": context.policy_epoch,
            "kill_switch_epoch": context.kill_switch_epoch,
            "portfolio_state_sequence": context.portfolio_state_sequence,
            "input_manifest_digest": context.input_manifest_digest,
            "portfolio_snapshot_digest": context.portfolio_snapshot_digest,
            "open_orders_snapshot_digest": context.open_orders_snapshot_digest,
            "market_data_snapshot_digest": context.market_data_snapshot_digest,
            "reference_data_snapshot_digest": context.reference_data_snapshot_digest,
            "fx_snapshot_digest": context.fx_snapshot_digest,
            "model_validation_manifest_digest": context.model_validation_manifest_digest,
        }
        actual = {name: getattr(payload, name) for name in expected}
        actual["environment"] = str(actual["environment"])
        if actual != expected:
            raise RiskVerificationError("decision context is stale or mismatched")
        if (
            bundle.tenant_id != context.tenant_id
            or str(bundle.environment) != context.environment
            or bundle.legal_entity_id != context.legal_entity_id
            or bundle.account_id != context.account_id
            or bundle.broker_id != context.broker_id
            or bundle.strategy_id != context.strategy_id
            or bundle.portfolio_state_sequence != context.portfolio_state_sequence
            or bundle.request_id != payload.request_id
            or bundle.case_id != payload.case_id
        ):
            raise RiskVerificationError("order bundle is outside the authorized context")
        bundle_digest = digest_canonical(bundle)
        if payload.approved_order_bundle_digest != bundle_digest:
            raise RiskVerificationError("exact approved order bundle digest does not match")
        return payload


class InMemoryDecisionConsumptionStore:
    """Atomic single-use nonce store for local tests only."""

    def __init__(self) -> None:
        self._consumed: set[tuple[str, str, str]] = set()
        self._lock = Lock()

    def consume(self, payload: RiskDecisionPayload) -> None:
        key = (payload.tenant_id, payload.account_id, payload.nonce)
        with self._lock:
            if key in self._consumed:
                raise RiskVerificationError("risk decision has already been consumed")
            self._consumed.add(key)


class ExecutionAuthorizationGate:
    """Single M0 entry point that verifies and atomically consumes a decision."""

    def __init__(
        self,
        verifier: RiskDecisionVerifier,
        consumption_store: InMemoryDecisionConsumptionStore,
    ) -> None:
        self._verifier = verifier
        self._consumption_store = consumption_store

    def authorize_once(
        self,
        decision: SignedRiskDecision,
        bundle: OrderBundle,
        context: RiskVerificationContext,
        *,
        now: datetime,
    ) -> RiskDecisionPayload:
        payload = self._verifier.verify(decision, bundle, context, now=now)
        self._consumption_store.consume(payload)
        return payload
