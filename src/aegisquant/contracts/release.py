"""Tamper-evident M6 production release prerequisites; never an order instruction."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.artifact import BlobRef
from aegisquant.contracts.common import Identifier, Sha256Digest, StrictModel, require_utc

ReleaseRole = Literal["INDEPENDENT_REVIEWER", "HUMAN_OPERATOR"]
ReleaseEvidenceName = Literal[
    "COMPLIANCE_POLICY_PACK",
    "DEPLOYMENT_ARTIFACT",
    "SBOM",
    "DATABASE_MIGRATION",
    "OBJECT_STORE_CONFORMANCE",
    "BACKUP_RESTORE_DRILL",
    "SERVICE_RECOVERY_DRILL",
    "SECURITY_ASSESSMENT",
    "MODEL_VALIDATION_MANIFEST",
    "LEGAL_COMPLIANCE",
    "DATA_RIGHTS",
    "BROKER_AGREEMENT",
    "RISK_POLICY",
    "NETWORK_POLICY",
    "SECRETS_MANAGEMENT",
]
_RELEASE_EVIDENCE_FIELDS: tuple[tuple[ReleaseEvidenceName, str], ...] = (
    ("COMPLIANCE_POLICY_PACK", "compliance_policy_pack_digest"),
    ("DEPLOYMENT_ARTIFACT", "deployment_artifact_digest"),
    ("SBOM", "sbom_digest"),
    ("DATABASE_MIGRATION", "database_migration_digest"),
    ("OBJECT_STORE_CONFORMANCE", "object_store_conformance_digest"),
    ("BACKUP_RESTORE_DRILL", "backup_restore_drill_digest"),
    ("SERVICE_RECOVERY_DRILL", "service_recovery_drill_digest"),
    ("SECURITY_ASSESSMENT", "security_assessment_digest"),
    ("MODEL_VALIDATION_MANIFEST", "model_validation_manifest_digest"),
    ("LEGAL_COMPLIANCE", "legal_compliance_digest"),
    ("DATA_RIGHTS", "data_rights_digest"),
    ("BROKER_AGREEMENT", "broker_agreement_digest"),
    ("RISK_POLICY", "risk_policy_digest"),
    ("NETWORK_POLICY", "network_policy_digest"),
    ("SECRETS_MANAGEMENT", "secrets_management_digest"),
)
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _parse_utc(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("release timestamps must be UTC datetimes")
    return require_utc(value)


def _exact_dns_hostname(value: str) -> str:
    if value != value.lower() or len(value) > 253 or "://" in value or ":" in value or "*" in value:
        raise ValueError("broker hostname must be an exact lowercase DNS name")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ValueError("broker hostname must not be an IP address")
    if "." not in value or any(not _DNS_LABEL.fullmatch(label) for label in value.split(".")):
        raise ValueError("broker hostname must be an exact lowercase DNS name")
    return value


class ReleaseEvidenceReference(StrictModel):
    evidence_name: ReleaseEvidenceName
    payload: BlobRef


class ProductionReleaseManifest(StrictModel):
    """Exact evidence set required before a venue-specific LIVE adapter may be activated."""

    schema_version: Literal[1] = 1
    profile: Literal["PERSONAL_LOCAL"] = "PERSONAL_LOCAL"
    requested_capability: Literal["LIVE_EXECUTION"] = "LIVE_EXECUTION"
    tenant_id: Identifier
    release_id: Identifier
    compliance_policy_pack_id: Identifier
    compliance_policy_pack_digest: Sha256Digest
    legal_entity_id: Identifier
    account_id: Identifier
    broker_id: Identifier
    broker_api_hostnames: tuple[str, ...]
    deployment_artifact_digest: Sha256Digest
    sbom_digest: Sha256Digest
    database_migration_digest: Sha256Digest
    object_store_conformance_digest: Sha256Digest
    backup_restore_drill_digest: Sha256Digest
    service_recovery_drill_digest: Sha256Digest
    security_assessment_digest: Sha256Digest
    model_validation_manifest_digest: Sha256Digest
    legal_compliance_digest: Sha256Digest
    data_rights_digest: Sha256Digest
    broker_agreement_digest: Sha256Digest
    risk_policy_digest: Sha256Digest
    network_policy_digest: Sha256Digest
    secrets_management_digest: Sha256Digest
    evidence_references: tuple[ReleaseEvidenceReference, ...]
    max_recovery_drill_age_seconds: int = Field(ge=1, le=90 * 24 * 60 * 60)
    created_at: datetime
    expires_at: datetime

    @field_validator("broker_api_hostnames", mode="before")
    @classmethod
    def hostname_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("evidence_references", mode="before")
    @classmethod
    def evidence_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("broker_api_hostnames")
    @classmethod
    def exact_hostnames(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_exact_dns_hostname(hostname) for hostname in value)
        if not checked or len(checked) > 8 or checked != tuple(sorted(set(checked))):
            raise ValueError("broker hostnames must be 1-8 unique sorted exact DNS names")
        return checked

    @field_validator("created_at", "expires_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)

    @model_validator(mode="after")
    def validity_window(self) -> ProductionReleaseManifest:
        if self.expires_at <= self.created_at:
            raise ValueError("release manifest validity window is invalid")
        expected_digests = {
            evidence_name: getattr(self, field_name)
            for evidence_name, field_name in _RELEASE_EVIDENCE_FIELDS
        }
        actual_names = tuple(reference.evidence_name for reference in self.evidence_references)
        if actual_names != tuple(expected_digests):
            raise ValueError("release evidence references must cover every named digest in order")
        if any(
            reference.payload.tenant_id != self.tenant_id
            or reference.payload.content_digest != expected_digests[reference.evidence_name]
            for reference in self.evidence_references
        ):
            raise ValueError(
                "release evidence references must bind the manifest tenant and digests"
            )
        return self


class ReleaseApprovalPayload(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    release_id: Identifier
    manifest_digest: Sha256Digest
    actor_id: Identifier
    role: ReleaseRole
    approved_at: datetime
    not_before: datetime
    expires_at: datetime

    @field_validator("approved_at", "not_before", "expires_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)

    @model_validator(mode="after")
    def validity_window(self) -> ReleaseApprovalPayload:
        if not self.approved_at <= self.not_before < self.expires_at:
            raise ValueError("release approval validity window is invalid")
        return self


class ReleaseAttestationHeader(StrictModel):
    typ: Literal["AQ-RELEASE-ATTESTATION"] = "AQ-RELEASE-ATTESTATION"
    schema_version: Literal[1] = 1
    alg: Literal["Ed25519"] = "Ed25519"
    key_id: Identifier


class SignedReleaseApproval(StrictModel):
    protected: ReleaseAttestationHeader
    payload: ReleaseApprovalPayload
    signature_b64url: str = Field(pattern=r"^[A-Za-z0-9_-]{86}$")


class TrustedReleaseKeyRecord(StrictModel):
    schema_version: Literal[1] = 1
    key_id: Identifier
    public_key_b64url: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    tenant_id: Identifier
    actor_id: Identifier
    allowed_roles: tuple[ReleaseRole, ...]
    valid_from: datetime
    valid_until: datetime
    revoked_at: datetime | None = None

    @field_validator("allowed_roles", mode="before")
    @classmethod
    def role_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("valid_from", "valid_until", "revoked_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> object:
        return None if value is None else _parse_utc(value)

    @model_validator(mode="after")
    def trusted_scope(self) -> TrustedReleaseKeyRecord:
        if self.valid_until <= self.valid_from:
            raise ValueError("release trust-key validity window is invalid")
        if not self.allowed_roles or len(self.allowed_roles) != len(set(self.allowed_roles)):
            raise ValueError("release trust key requires unique allowed roles")
        return self


class ReleaseVerificationInput(StrictModel):
    schema_version: Literal[1] = 1
    manifest: ProductionReleaseManifest
    independent_review: SignedReleaseApproval
    operator_approval: SignedReleaseApproval


class ReleaseTrustStore(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    trusted_keys: tuple[TrustedReleaseKeyRecord, ...]

    @field_validator("trusted_keys", mode="before")
    @classmethod
    def key_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def tenant_and_keys(self) -> ReleaseTrustStore:
        if not self.trusted_keys or any(
            key.tenant_id != self.tenant_id for key in self.trusted_keys
        ):
            raise ValueError("release trust store keys must share its tenant")
        return self
