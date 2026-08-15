from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegisquant.case_cli import main
from aegisquant.contracts.artifact import BlobRef
from aegisquant.contracts.release import ProductionReleaseManifest, ReleaseEvidenceReference
from aegisquant.contracts.risk import (
    DecisionOutcome,
    OrderBundle,
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecisionPayload,
    RiskTrustStore,
    TimeInForce,
    TradingEnvironment,
    TrustedRiskKeyRecord,
)
from aegisquant.contracts.venue import (
    VenueAdapterProfile,
    VenueConformanceInput,
    VenueOrderAcknowledgement,
    VenueOrderLifecycleEvidence,
    VenueRiskAuthorization,
    VenueRiskContext,
    VenueSubmissionCommand,
)
from aegisquant.security.digests import digest_canonical
from aegisquant.security.risk_signing import (
    RiskDecisionSigner,
    RiskVerificationError,
    TrustedRiskKey,
    load_risk_trust_store,
    trusted_risk_keys_from_store,
)
from aegisquant.venue.conformance import VenueConformanceError, verify_venue_conformance

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


def sha(character: str) -> str:
    return "sha256:" + character * 64


def release() -> ProductionReleaseManifest:
    evidence = (
        ("COMPLIANCE_POLICY_PACK", sha("1")),
        ("DEPLOYMENT_ARTIFACT", sha("2")),
        ("SBOM", sha("3")),
        ("DATABASE_MIGRATION", sha("4")),
        ("OBJECT_STORE_CONFORMANCE", sha("5")),
        ("BACKUP_RESTORE_DRILL", sha("6")),
        ("SERVICE_RECOVERY_DRILL", sha("7")),
        ("SECURITY_ASSESSMENT", sha("8")),
        ("MODEL_VALIDATION_MANIFEST", sha("9")),
        ("LEGAL_COMPLIANCE", sha("a")),
        ("DATA_RIGHTS", sha("b")),
        ("BROKER_AGREEMENT", sha("c")),
        ("RISK_POLICY", sha("d")),
        ("NETWORK_POLICY", sha("e")),
        ("SECRETS_MANAGEMENT", sha("f")),
    )
    return ProductionReleaseManifest(
        tenant_id="tenant-a",
        release_id="release-a",
        compliance_policy_pack_id="policy-pack-a",
        compliance_policy_pack_digest=sha("1"),
        legal_entity_id="legal-entity-a",
        account_id="account-a",
        broker_id="venue-a",
        broker_api_hostnames=("api.venue.example",),
        deployment_artifact_digest=sha("2"),
        sbom_digest=sha("3"),
        database_migration_digest=sha("4"),
        object_store_conformance_digest=sha("5"),
        backup_restore_drill_digest=sha("6"),
        service_recovery_drill_digest=sha("7"),
        security_assessment_digest=sha("8"),
        model_validation_manifest_digest=sha("9"),
        legal_compliance_digest=sha("a"),
        data_rights_digest=sha("b"),
        broker_agreement_digest=sha("c"),
        risk_policy_digest=sha("d"),
        network_policy_digest=sha("e"),
        secrets_management_digest=sha("f"),
        evidence_references=tuple(
            ReleaseEvidenceReference(
                evidence_name=name,  # type: ignore[arg-type]
                payload=BlobRef(
                    tenant_id="tenant-a",
                    uri=f"file:///private/aegisquant/{name.lower()}",
                    content_digest=digest,
                    size_bytes=1,
                    media_type="application/json",
                    retention_class="release-evidence",
                ),
            )
            for name, digest in evidence
        ),
        max_recovery_drill_age_seconds=30 * 24 * 60 * 60,
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )


def bundle() -> OrderBundle:
    return OrderBundle(
        tenant_id="tenant-a",
        environment=TradingEnvironment.PAPER,
        legal_entity_id="legal-entity-a",
        account_id="account-a",
        broker_id="venue-a",
        strategy_id="strategy-a",
        case_id=UUID("00000000-0000-0000-0000-000000000101"),
        request_id=UUID("00000000-0000-0000-0000-000000000102"),
        portfolio_state_sequence=7,
        orders=(
            OrderIntent(
                client_order_id="order-a",
                instrument_id="AAA",
                instrument_version="aaa-v1",
                venue_id="venue-a",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                quantity=Decimal("1"),
                currency="USD",
            ),
            OrderIntent(
                client_order_id="order-b",
                instrument_id="BBB",
                instrument_version="bbb-v1",
                venue_id="venue-a",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
                quantity=Decimal("2"),
                limit_price=Decimal("10"),
                currency="USD",
            ),
        ),
    )


def profile() -> VenueAdapterProfile:
    return VenueAdapterProfile(
        adapter_id="venue-conformance-v1",
        broker_id="venue-a",
        compliance_policy_pack_id="policy-pack-a",
        compliance_policy_pack_digest=sha("1"),
        allowed_hostnames=("api.venue.example",),
        supported_order_types=(OrderType.LIMIT, OrderType.MARKET),
        supports_client_order_idempotency=True,
        supports_order_status_retrieval=True,
        supports_cancellation=True,
        max_submission_timeout_seconds=10,
        reviewed_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )


def authorization() -> VenueRiskAuthorization:
    value = bundle()
    decision = RiskDecisionSigner("risk-key-a", risk_private_key()).sign(
        RiskDecisionPayload(
            tenant_id=value.tenant_id,
            decision_id=UUID("00000000-0000-0000-0000-000000000103"),
            request_id=value.request_id,
            case_id=value.case_id,
            issuance_sequence=1,
            nonce="1" * 32,
            environment=value.environment,
            legal_entity_id=value.legal_entity_id,
            account_id=value.account_id,
            broker_id=value.broker_id,
            strategy_id=value.strategy_id,
            outcome=DecisionOutcome.APPROVE,
            policy_bundle_digest=sha("d"),
            policy_epoch=3,
            kill_switch_epoch=4,
            input_manifest_digest=sha("a"),
            portfolio_state_sequence=value.portfolio_state_sequence,
            portfolio_snapshot_digest=sha("b"),
            open_orders_snapshot_digest=sha("c"),
            market_data_snapshot_digest=sha("d"),
            reference_data_snapshot_digest=sha("e"),
            fx_snapshot_digest=sha("f"),
            model_validation_manifest_digest=sha("9"),
            execution_plan_digest=sha("1"),
            requested_order_bundle_digest=digest_canonical(value),
            approved_order_bundle_digest=digest_canonical(value),
            rule_results=(),
            created_at=NOW,
            not_before=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
    )
    return VenueRiskAuthorization(
        decision=decision,
        context=VenueRiskContext(
            tenant_id=value.tenant_id,
            environment=value.environment,
            legal_entity_id=value.legal_entity_id,
            account_id=value.account_id,
            broker_id=value.broker_id,
            strategy_id=value.strategy_id,
            policy_epoch=3,
            kill_switch_epoch=4,
            portfolio_state_sequence=value.portfolio_state_sequence,
            input_manifest_digest=sha("a"),
            portfolio_snapshot_digest=sha("b"),
            open_orders_snapshot_digest=sha("c"),
            market_data_snapshot_digest=sha("d"),
            reference_data_snapshot_digest=sha("e"),
            fx_snapshot_digest=sha("f"),
            model_validation_manifest_digest=sha("9"),
        ),
    )


def risk_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(b"\x44" * 32)


def risk_trust_store() -> RiskTrustStore:
    public_key = (
        risk_private_key()
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    return RiskTrustStore(
        tenant_id="tenant-a",
        trusted_keys=(
            TrustedRiskKeyRecord(
                key_id="risk-key-a",
                public_key_b64url=base64.urlsafe_b64encode(public_key).rstrip(b"=").decode(),
                tenant_id="tenant-a",
                valid_from=NOW - timedelta(days=1),
                valid_until=NOW + timedelta(days=1),
            ),
        ),
    )


def trusted_risk_keys() -> dict[str, TrustedRiskKey]:
    return trusted_risk_keys_from_store(risk_trust_store())


def command() -> VenueSubmissionCommand:
    value = bundle()
    risk = authorization()
    return VenueSubmissionCommand(
        tenant_id=value.tenant_id,
        release_manifest_digest=digest_canonical(release()),
        compliance_policy_pack_id="policy-pack-a",
        compliance_policy_pack_digest=sha("1"),
        legal_entity_id=value.legal_entity_id,
        account_id=value.account_id,
        broker_id=value.broker_id,
        request_id=value.request_id,
        order_bundle_digest=digest_canonical(value),
        risk_decision_digest=digest_canonical(risk.decision),
        risk_nonce=risk.decision.payload.nonce,
        client_order_ids=tuple(order.client_order_id for order in value.orders),
        submission_hostname="api.venue.example",
        not_before=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def acknowledgements(value: VenueSubmissionCommand) -> tuple[VenueOrderAcknowledgement, ...]:
    command_digest = digest_canonical(value)
    return tuple(
        VenueOrderAcknowledgement(
            tenant_id=value.tenant_id,
            account_id=value.account_id,
            broker_id=value.broker_id,
            command_digest=command_digest,
            client_order_id=client_order_id,
            venue_order_id=f"venue-{client_order_id}",
            status="ACCEPTED",
            observed_at=NOW + timedelta(seconds=1),
        )
        for client_order_id in value.client_order_ids
    )


def lifecycles(value: VenueSubmissionCommand) -> tuple[VenueOrderLifecycleEvidence, ...]:
    return tuple(
        VenueOrderLifecycleEvidence(
            client_order_id=acknowledgement.client_order_id,
            first_attempt_at=NOW,
            timeout_at=NOW + timedelta(seconds=1),
            retry_acknowledgement=acknowledgement,
            status_venue_order_id=acknowledgement.venue_order_id,
            status="OPEN",
            status_observed_at=NOW + timedelta(seconds=3),
            cancellation_venue_order_id=acknowledgement.venue_order_id,
            cancellation_status="CANCELLED",
            cancelled_at=NOW + timedelta(seconds=4),
        )
        for acknowledgement in acknowledgements(value)
    )


def test_fixture_venue_conformance_binds_exact_release_policy_and_orders() -> None:
    value = command()

    report = verify_venue_conformance(
        release(),
        profile(),
        bundle(),
        value,
        risk_authorization=authorization(),
        trusted_risk_keys=trusted_risk_keys(),
        lifecycles=lifecycles(value),
        now=NOW + timedelta(seconds=5),
    )

    assert report.command_digest == digest_canonical(value)
    assert report.acknowledged_order_ids == value.client_order_ids
    assert report.outcome == "CONFORMANT"


def test_venue_conformance_rejects_an_unbound_order_bundle() -> None:
    value = command()

    with pytest.raises(VenueConformanceError, match="risk authorization"):
        verify_venue_conformance(
            release(),
            profile(),
            bundle(),
            value,
            now=NOW + timedelta(seconds=2),
        )


def test_venue_conformance_rejects_an_untrusted_risk_key() -> None:
    value = command()

    with pytest.raises(VenueConformanceError, match="risk authorization"):
        verify_venue_conformance(
            release(),
            profile(),
            bundle(),
            value,
            risk_authorization=authorization(),
            trusted_risk_keys={},
            lifecycles=lifecycles(value),
            now=NOW + timedelta(seconds=5),
        )


def test_venue_conformance_rejects_future_lifecycle_evidence() -> None:
    value = command()

    with pytest.raises(VenueConformanceError, match="lifecycle"):
        verify_venue_conformance(
            release(),
            profile(),
            bundle(),
            value,
            risk_authorization=authorization(),
            trusted_risk_keys=trusted_risk_keys(),
            lifecycles=lifecycles(value),
            now=NOW + timedelta(seconds=2),
        )


def test_venue_conformance_rejects_mismatched_signed_risk_context() -> None:
    value = command()
    risk = authorization()
    mismatched = risk.model_copy(
        update={"context": risk.context.model_copy(update={"kill_switch_epoch": 5})}
    )

    with pytest.raises(VenueConformanceError, match="risk authorization"):
        verify_venue_conformance(
            release(),
            profile(),
            bundle(),
            value,
            risk_authorization=mismatched,
            trusted_risk_keys=trusted_risk_keys(),
            lifecycles=lifecycles(value),
            now=NOW + timedelta(seconds=5),
        )


@pytest.mark.parametrize(
    ("lifecycle", "error"),
    [
        (
            lambda value: lifecycles(value)[0].model_copy(
                update={
                    "retry_acknowledgement": lifecycles(value)[0].retry_acknowledgement.model_copy(
                        update={"status": "REJECTED"}
                    )
                }
            ),
            "lifecycle",
        ),
        (
            lambda value: lifecycles(value)[0].model_copy(
                update={"status_venue_order_id": "different-venue-order"}
            ),
            "lifecycle",
        ),
        (
            lambda value: lifecycles(value)[0].model_copy(
                update={"cancellation_venue_order_id": "different-venue-order"}
            ),
            "lifecycle",
        ),
    ],
)
def test_venue_conformance_rejects_incomplete_lifecycle_evidence(
    lifecycle: Callable[[VenueSubmissionCommand], VenueOrderLifecycleEvidence], error: str
) -> None:
    value = command()
    changed = lifecycle(value)
    evidence = (changed, *lifecycles(value)[1:])

    with pytest.raises(VenueConformanceError, match=error):
        verify_venue_conformance(
            release(),
            profile(),
            bundle(),
            value,
            risk_authorization=authorization(),
            trusted_risk_keys=trusted_risk_keys(),
            lifecycles=evidence,
            now=NOW + timedelta(seconds=5),
        )


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"submission_hostname": "other.venue.example"}, "hostname"),
        ({"compliance_policy_pack_digest": sha("f")}, "policy pack"),
        ({"client_order_ids": ("order-b", "order-a")}, "order IDs"),
    ],
)
def test_venue_conformance_rejects_unbound_command(change: dict[str, object], error: str) -> None:
    value = command().model_copy(update=change)

    with pytest.raises(VenueConformanceError, match=error):
        verify_venue_conformance(
            release(),
            profile(),
            bundle(),
            value,
            risk_authorization=authorization(),
            trusted_risk_keys=trusted_risk_keys(),
            lifecycles=lifecycles(value),
            now=NOW + timedelta(seconds=2),
        )


def test_venue_conformance_rejects_duplicate_or_wrong_acknowledgement() -> None:
    value = command()
    repeated = (*lifecycles(value), lifecycles(value)[0])

    with pytest.raises(VenueConformanceError, match="lifecycle"):
        verify_venue_conformance(
            release(),
            profile(),
            bundle(),
            value,
            risk_authorization=authorization(),
            trusted_risk_keys=trusted_risk_keys(),
            lifecycles=repeated,
            now=NOW + timedelta(seconds=2),
        )


def test_venue_cli_verifies_recorded_fixture_without_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    value = command()
    input_path = tmp_path / "venue.json"
    trust_path = tmp_path / "risk-trust.json"
    input_path.write_text(
        VenueConformanceInput(
            release=release(),
            profile=profile(),
            order_bundle=bundle(),
            command=value,
            risk_authorization=authorization(),
            lifecycles=lifecycles(value),
            now=NOW + timedelta(seconds=5),
        ).model_dump_json(),
        encoding="utf-8",
    )
    trust_path.write_text(risk_trust_store().model_dump_json(), encoding="utf-8")
    trust_path.chmod(0o600)

    assert main(["venue", "verify", str(input_path), "--risk-trust-store", str(trust_path)]) == 0
    assert '"outcome": "CONFORMANT"' in capsys.readouterr().out


def test_risk_trust_store_rejects_group_writable_file(tmp_path: Path) -> None:
    trust_path = tmp_path / "risk-trust.json"
    trust_path.write_text(risk_trust_store().model_dump_json(), encoding="utf-8")
    trust_path.chmod(0o620)

    with pytest.raises(RiskVerificationError, match="permissions"):
        load_risk_trust_store(trust_path)
