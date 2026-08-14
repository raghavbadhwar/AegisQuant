"""Fail-closed Ed25519 verification for M6 production release prerequisites."""

from __future__ import annotations

import base64
import os
import stat
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from aegisquant.contracts.common import canonical_json_bytes, require_utc
from aegisquant.contracts.release import (
    ProductionReleaseManifest,
    ReleaseApprovalPayload,
    ReleaseAttestationHeader,
    ReleaseTrustStore,
    SignedReleaseApproval,
    TrustedReleaseKeyRecord,
)
from aegisquant.security.digests import digest_canonical

RELEASE_APPROVAL_DOMAIN = b"AEGISQUANT_RELEASE_APPROVAL_V1\0"


class ReleaseAttestationError(ValueError):
    pass


def load_release_trust_store(path: Path) -> ReleaseTrustStore:
    """Load an operator-owned policy file that no group or other user can modify."""

    if not path.is_absolute():
        raise ReleaseAttestationError("release trust store path must be absolute")
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            data = stream.read(1_048_577)
    except OSError as exc:
        raise ReleaseAttestationError("release trust store cannot be read") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or len(data) > 1_048_576
    ):
        raise ReleaseAttestationError("release trust store ownership or permissions are unsafe")
    try:
        return ReleaseTrustStore.model_validate_json(data)
    except ValueError as exc:
        raise ReleaseAttestationError("release trust store is invalid") from exc


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signing_bytes(header: ReleaseAttestationHeader, payload: ReleaseApprovalPayload) -> bytes:
    return RELEASE_APPROVAL_DOMAIN + canonical_json_bytes({"protected": header, "payload": payload})


class ReleaseAttestationSigner:
    """Development signer; production keys must remain in an OS/HSM signing boundary."""

    def __init__(self, key_id: str, private_key: Ed25519PrivateKey) -> None:
        self._key_id = key_id
        self._private_key = private_key

    def sign(self, payload: ReleaseApprovalPayload) -> SignedReleaseApproval:
        header = ReleaseAttestationHeader(key_id=self._key_id)
        return SignedReleaseApproval(
            protected=header,
            payload=payload,
            signature_b64url=_b64url(self._private_key.sign(_signing_bytes(header, payload))),
        )


class ProductionReleaseVerifier:
    def __init__(self, trusted_keys: tuple[TrustedReleaseKeyRecord, ...]) -> None:
        keys = {key.key_id: key for key in trusted_keys}
        if not keys or len(keys) != len(trusted_keys):
            raise ReleaseAttestationError("release trust store is empty or has duplicate key IDs")
        self._trusted_keys = keys

    def _verify_approval(
        self,
        approval: SignedReleaseApproval,
        manifest: ProductionReleaseManifest,
        *,
        required_role: str,
        now: datetime,
    ) -> ReleaseApprovalPayload:
        now = require_utc(now)
        payload = approval.payload
        trusted = self._trusted_keys.get(approval.protected.key_id)
        if trusted is None:
            raise ReleaseAttestationError("untrusted release attestation key")
        if (
            payload.role != required_role
            or payload.actor_id != trusted.actor_id
            or payload.tenant_id != trusted.tenant_id
            or payload.role not in trusted.allowed_roles
            or payload.approved_at < trusted.valid_from
            or payload.approved_at >= trusted.valid_until
            or (trusted.revoked_at is not None and payload.approved_at >= trusted.revoked_at)
            or now < payload.approved_at
            or now < trusted.valid_from
            or now >= trusted.valid_until
            or (trusted.revoked_at is not None and now >= trusted.revoked_at)
        ):
            raise ReleaseAttestationError("release attestation key is outside trusted scope")
        if now < payload.not_before or now >= payload.expires_at:
            raise ReleaseAttestationError("release approval is outside its validity window")
        try:
            public_key_bytes = _b64url_decode(trusted.public_key_b64url)
            if len(public_key_bytes) != 32:
                raise ValueError("wrong Ed25519 public-key length")
            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                _b64url_decode(approval.signature_b64url),
                _signing_bytes(approval.protected, payload),
            )
        except (InvalidSignature, ValueError) as exc:
            raise ReleaseAttestationError("invalid release attestation signature") from exc
        if (
            payload.tenant_id != manifest.tenant_id
            or payload.release_id != manifest.release_id
            or payload.manifest_digest != digest_canonical(manifest)
            or payload.approved_at < manifest.created_at
            or payload.approved_at >= manifest.expires_at
        ):
            raise ReleaseAttestationError("release approval manifest digest or scope is mismatched")
        return payload

    def verify(
        self,
        manifest: ProductionReleaseManifest,
        *,
        independent_review: SignedReleaseApproval,
        operator_approval: SignedReleaseApproval,
        now: datetime,
    ) -> ProductionReleaseManifest:
        now = require_utc(now)
        if now < manifest.created_at or now >= manifest.expires_at:
            raise ReleaseAttestationError("release manifest is not current")
        review = self._verify_approval(
            independent_review,
            manifest,
            required_role="INDEPENDENT_REVIEWER",
            now=now,
        )
        operator = self._verify_approval(
            operator_approval,
            manifest,
            required_role="HUMAN_OPERATOR",
            now=now,
        )
        if (
            review.actor_id == operator.actor_id
            or independent_review.protected.key_id == operator_approval.protected.key_id
            or operator.approved_at <= review.approved_at
        ):
            raise ReleaseAttestationError(
                "release review and later operator approval must be independent"
            )
        return manifest
