"""Ed25519 attestations for independent learning evaluation and human approval."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from aegisquant.contracts.common import canonical_json_bytes, require_utc
from aegisquant.contracts.learning import (
    LearningAttestationHeader,
    LearningEvaluationV2,
    PromotionApprovalV2,
    SignedLearningEvaluation,
    SignedPromotionApproval,
)

EVALUATION_DOMAIN = b"AEGISQUANT_LEARNING_EVALUATION_V1\0"
APPROVAL_DOMAIN = b"AEGISQUANT_LEARNING_APPROVAL_V1\0"


class LearningAttestationError(ValueError):
    pass


def _signing_bytes(
    domain: bytes,
    header: LearningAttestationHeader,
    payload: LearningEvaluationV2 | PromotionApprovalV2,
) -> bytes:
    return domain + canonical_json_bytes({"protected": header, "payload": payload})


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class LearningAttestationSigner:
    def __init__(self, key_id: str, private_key: Ed25519PrivateKey) -> None:
        self._key_id = key_id
        self._private_key = private_key

    def sign_evaluation(self, payload: LearningEvaluationV2) -> SignedLearningEvaluation:
        header = LearningAttestationHeader(key_id=self._key_id)
        return SignedLearningEvaluation(
            protected=header,
            payload=payload,
            signature_b64url=_b64url(
                self._private_key.sign(_signing_bytes(EVALUATION_DOMAIN, header, payload))
            ),
        )

    def sign_approval(self, payload: PromotionApprovalV2) -> SignedPromotionApproval:
        header = LearningAttestationHeader(key_id=self._key_id)
        return SignedPromotionApproval(
            protected=header,
            payload=payload,
            signature_b64url=_b64url(
                self._private_key.sign(_signing_bytes(APPROVAL_DOMAIN, header, payload))
            ),
        )


@dataclass(frozen=True)
class TrustedLearningKey:
    public_key: Ed25519PublicKey
    valid_from: datetime
    valid_until: datetime
    actor_id: str
    tenant_id: str
    allowed_roles: frozenset[str]
    revoked_at: datetime | None = None


class LearningAttestationVerifier:
    def __init__(self, trusted_keys: dict[str, TrustedLearningKey]) -> None:
        self._trusted_keys = dict(trusted_keys)

    def _verify(
        self,
        *,
        key_id: str,
        signature: str,
        domain: bytes,
        header: LearningAttestationHeader,
        payload: LearningEvaluationV2 | PromotionApprovalV2,
        actor_id: str,
        role: str,
        at: datetime,
        now: datetime,
    ) -> None:
        trusted = self._trusted_keys.get(key_id)
        at = require_utc(at)
        now = require_utc(now)
        if trusted is None:
            raise LearningAttestationError("untrusted learning attestation key")
        if (
            trusted.actor_id != actor_id
            or trusted.tenant_id != payload.tenant_id
            or role not in trusted.allowed_roles
            or at < require_utc(trusted.valid_from)
            or at >= require_utc(trusted.valid_until)
            or (trusted.revoked_at is not None and at >= require_utc(trusted.revoked_at))
            or now < at
            or now < require_utc(trusted.valid_from)
            or now >= require_utc(trusted.valid_until)
            or (trusted.revoked_at is not None and now >= require_utc(trusted.revoked_at))
        ):
            raise LearningAttestationError("learning attestation key is outside trusted scope")
        try:
            trusted.public_key.verify(
                _b64url_decode(signature),
                _signing_bytes(domain, header, payload),
            )
        except (InvalidSignature, ValueError) as exc:
            raise LearningAttestationError("invalid learning attestation signature") from exc

    def verify_evaluation(
        self, value: SignedLearningEvaluation, *, now: datetime
    ) -> LearningEvaluationV2:
        self._verify(
            key_id=value.protected.key_id,
            signature=value.signature_b64url,
            domain=EVALUATION_DOMAIN,
            header=value.protected,
            payload=value.payload,
            actor_id=value.payload.evaluator_id,
            role="EVALUATOR",
            at=value.payload.evaluated_at,
            now=now,
        )
        return value.payload

    def verify_approval(
        self, value: SignedPromotionApproval, *, now: datetime
    ) -> PromotionApprovalV2:
        self._verify(
            key_id=value.protected.key_id,
            signature=value.signature_b64url,
            domain=APPROVAL_DOMAIN,
            header=value.protected,
            payload=value.payload,
            actor_id=value.payload.approver_id,
            role="HUMAN_APPROVER",
            at=value.payload.approved_at,
            now=now,
        )
        now = require_utc(now)
        if now < value.payload.not_before or now >= value.payload.expires_at:
            raise LearningAttestationError("promotion approval is outside its validity window")
        return value.payload
