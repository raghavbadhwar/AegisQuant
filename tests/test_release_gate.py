from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import aegisquant.case_cli as case_cli
from aegisquant.case_cli import main
from aegisquant.contracts.artifact import BlobRef
from aegisquant.contracts.recovery import (
    ObjectStoreRecoveryReceipt,
    object_store_content_manifest_digest,
    object_store_recovery_receipt_digest,
)
from aegisquant.contracts.release import (
    ProductionReleaseManifest,
    ReleaseApprovalPayload,
    ReleaseTrustStore,
    ReleaseVerificationInput,
    TrustedReleaseKeyRecord,
)
from aegisquant.security.digests import digest_canonical
from aegisquant.security.release_attestation import (
    ProductionReleaseVerifier,
    ReleaseAttestationError,
    ReleaseAttestationSigner,
    load_release_trust_store,
)

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


def sha(character: str) -> str:
    return "sha256:" + character * 64


def manifest(*, backup_restore_drill_digest: str = sha("5")) -> ProductionReleaseManifest:
    return ProductionReleaseManifest(
        tenant_id="tenant-personal",
        release_id="release-2026-08-14",
        compliance_policy_pack_id="policy-pack-reviewed",
        compliance_policy_pack_digest=sha("0"),
        legal_entity_id="operator-personal",
        account_id="broker-account-primary",
        broker_id="broker-selected",
        broker_api_hostnames=("api.broker.example",),
        deployment_artifact_digest=sha("1"),
        sbom_digest=sha("2"),
        database_migration_digest=sha("3"),
        object_store_conformance_digest=sha("4"),
        backup_restore_drill_digest=backup_restore_drill_digest,
        service_recovery_drill_digest=sha("6"),
        security_assessment_digest=sha("7"),
        model_validation_manifest_digest=sha("8"),
        legal_compliance_digest=sha("9"),
        data_rights_digest=sha("a"),
        broker_agreement_digest=sha("b"),
        risk_policy_digest=sha("c"),
        network_policy_digest=sha("d"),
        secrets_management_digest=sha("e"),
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )


def raw_public_key(key: Ed25519PrivateKey) -> str:
    data = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def verified_input(
    *, backup_restore_drill_digest: str = sha("5")
) -> tuple[ReleaseVerificationInput, ReleaseTrustStore, datetime]:
    release = manifest(backup_restore_drill_digest=backup_restore_drill_digest)
    release_digest = digest_canonical(release)
    reviewer_key = Ed25519PrivateKey.from_private_bytes(b"\x31" * 32)
    operator_key = Ed25519PrivateKey.from_private_bytes(b"\x32" * 32)
    reviewer = ReleaseApprovalPayload(
        tenant_id=release.tenant_id,
        release_id=release.release_id,
        manifest_digest=release_digest,
        actor_id="independent-reviewer",
        role="INDEPENDENT_REVIEWER",
        approved_at=NOW + timedelta(minutes=1),
        not_before=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(days=2),
    )
    operator = ReleaseApprovalPayload(
        tenant_id=release.tenant_id,
        release_id=release.release_id,
        manifest_digest=release_digest,
        actor_id="human-operator",
        role="HUMAN_OPERATOR",
        approved_at=NOW + timedelta(minutes=2),
        not_before=NOW + timedelta(minutes=2),
        expires_at=NOW + timedelta(days=2),
    )
    request = ReleaseVerificationInput(
        manifest=release,
        independent_review=ReleaseAttestationSigner("release-reviewer-1", reviewer_key).sign(
            reviewer
        ),
        operator_approval=ReleaseAttestationSigner("release-operator-1", operator_key).sign(
            operator
        ),
    )
    trust_store = ReleaseTrustStore(
        tenant_id=release.tenant_id,
        trusted_keys=(
            TrustedReleaseKeyRecord(
                key_id="release-reviewer-1",
                public_key_b64url=raw_public_key(reviewer_key),
                tenant_id=release.tenant_id,
                actor_id=reviewer.actor_id,
                allowed_roles=("INDEPENDENT_REVIEWER",),
                valid_from=NOW - timedelta(days=1),
                valid_until=NOW + timedelta(days=30),
            ),
            TrustedReleaseKeyRecord(
                key_id="release-operator-1",
                public_key_b64url=raw_public_key(operator_key),
                tenant_id=release.tenant_id,
                actor_id=operator.actor_id,
                allowed_roles=("HUMAN_OPERATOR",),
                valid_from=NOW - timedelta(days=1),
                valid_until=NOW + timedelta(days=30),
            ),
        ),
    )
    return request, trust_store, NOW + timedelta(hours=1)


def recovery_receipt() -> ObjectStoreRecoveryReceipt:
    reference = BlobRef(
        tenant_id="tenant-personal",
        uri="file:///private/aegisquant/recovered/object",
        content_digest=sha("f"),
        size_bytes=1,
        media_type="text/plain",
        retention_class="ops",
    )
    content_manifest_digest = object_store_content_manifest_digest((reference,))
    return ObjectStoreRecoveryReceipt(
        tenant_id="tenant-personal",
        drill_id="recovery-drill-a",
        source_content_manifest_digest=content_manifest_digest,
        recovered_content_manifest_digest=content_manifest_digest,
        recovered_references=(reference,),
        object_count=1,
        total_bytes=1,
        recovery_digest=object_store_recovery_receipt_digest(
            tenant_id="tenant-personal",
            drill_id="recovery-drill-a",
            source_content_manifest_digest=content_manifest_digest,
            recovered_content_manifest_digest=content_manifest_digest,
            recovered_references=(reference,),
            object_count=1,
            total_bytes=1,
            completed_at=NOW,
        ),
        completed_at=NOW,
    )


def test_release_gate_requires_exact_independent_current_approvals() -> None:
    request, trust_store, now = verified_input()

    result = ProductionReleaseVerifier(trust_store.trusted_keys).verify(
        request.manifest,
        independent_review=request.independent_review,
        operator_approval=request.operator_approval,
        now=now,
    )

    assert result == request.manifest


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"deployment_artifact_digest": sha("f")}, "manifest digest"),
        ({"expires_at": NOW + timedelta(minutes=30)}, "manifest is not current"),
    ],
)
def test_release_gate_rejects_tampered_or_expired_manifest(
    change: dict[str, object], error: str
) -> None:
    request, trust_store, now = verified_input()
    changed = request.manifest.model_copy(update=change)

    with pytest.raises(ReleaseAttestationError, match=error):
        ProductionReleaseVerifier(trust_store.trusted_keys).verify(
            changed,
            independent_review=request.independent_review,
            operator_approval=request.operator_approval,
            now=now,
        )


def test_release_gate_rejects_same_actor_or_revoked_current_key() -> None:
    request, trust_store, now = verified_input()
    operator_key = Ed25519PrivateKey.from_private_bytes(b"\x32" * 32)
    same_actor_payload = request.operator_approval.payload.model_copy(
        update={"actor_id": request.independent_review.payload.actor_id}
    )
    same_actor = ReleaseAttestationSigner("release-operator-1", operator_key).sign(
        same_actor_payload
    )
    same_actor_trust = tuple(
        key.model_copy(update={"actor_id": same_actor_payload.actor_id})
        if key.key_id == same_actor.protected.key_id
        else key
        for key in trust_store.trusted_keys
    )
    with pytest.raises(ReleaseAttestationError, match="independent"):
        ProductionReleaseVerifier(same_actor_trust).verify(
            request.manifest,
            independent_review=request.independent_review,
            operator_approval=same_actor,
            now=now,
        )

    revoked = tuple(
        key.model_copy(update={"revoked_at": NOW + timedelta(minutes=30)})
        if key.key_id == request.operator_approval.protected.key_id
        else key
        for key in trust_store.trusted_keys
    )
    with pytest.raises(ReleaseAttestationError, match="outside trusted scope"):
        ProductionReleaseVerifier(revoked).verify(
            request.manifest,
            independent_review=request.independent_review,
            operator_approval=request.operator_approval,
            now=now,
        )


@pytest.mark.parametrize(
    "hostname",
    ("https://api.broker.example", "*.broker.example", "127.0.0.1", "broker.example:443"),
)
def test_release_manifest_requires_exact_dns_hostnames(hostname: str) -> None:
    with pytest.raises(ValueError, match="hostname"):
        ProductionReleaseManifest.model_validate(
            manifest().model_dump(mode="python") | {"broker_api_hostnames": (hostname,)}
        )


def test_release_cli_verifies_signatures_and_actual_runtime_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt = recovery_receipt()
    request, trust_store, now = verified_input(
        backup_restore_drill_digest=digest_canonical(receipt)
    )
    request_path = tmp_path / "release.json"
    trust_path = tmp_path / "release-trust.json"
    receipt_path = tmp_path / "recovery.json"
    object_root = tmp_path / "objects"
    request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")
    trust_path.write_text(trust_store.model_dump_json(indent=2), encoding="utf-8")
    receipt_path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")
    trust_path.chmod(0o600)

    async def dependencies() -> dict[str, bool]:
        return {"postgresql": True, "temporal": True}

    monkeypatch.setattr(case_cli, "dependency_readiness", dependencies)
    monkeypatch.setattr(case_cli, "_now", lambda: now)
    monkeypatch.setenv("AEGISQUANT_OBJECT_STORE_ROOT", str(object_root))

    assert (
        main(
            [
                "release",
                "verify",
                str(request_path),
                "--trust-store",
                str(trust_path),
                "--recovery-receipt",
                str(receipt_path),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"prerequisites_verified": true' in output
    assert '"live_execution_enabled": false' in output
    assert '"object_store": true' in output


def test_release_trust_store_rejects_group_writable_file(
    tmp_path: Path,
) -> None:
    _, trust_store, _ = verified_input()
    trust_path = tmp_path / "release-trust.json"
    trust_path.write_text(trust_store.model_dump_json(), encoding="utf-8")
    trust_path.chmod(0o620)

    with pytest.raises(ReleaseAttestationError, match="permissions"):
        load_release_trust_store(trust_path)


def test_release_trust_store_rejects_symlink(tmp_path: Path) -> None:
    _, trust_store, _ = verified_input()
    target = tmp_path / "target.json"
    link = tmp_path / "release-trust.json"
    target.write_text(trust_store.model_dump_json(), encoding="utf-8")
    target.chmod(0o600)
    link.symlink_to(target)

    with pytest.raises(ReleaseAttestationError, match="cannot be read"):
        load_release_trust_store(link)
