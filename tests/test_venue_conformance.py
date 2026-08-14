from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from aegisquant.case_cli import main
from aegisquant.contracts.release import ProductionReleaseManifest
from aegisquant.contracts.risk import (
    OrderBundle,
    OrderIntent,
    OrderSide,
    OrderType,
    TimeInForce,
    TradingEnvironment,
)
from aegisquant.contracts.venue import (
    VenueAdapterProfile,
    VenueConformanceInput,
    VenueOrderAcknowledgement,
    VenueSubmissionCommand,
)
from aegisquant.security.digests import digest_canonical
from aegisquant.venue.conformance import VenueConformanceError, verify_venue_conformance

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


def sha(character: str) -> str:
    return "sha256:" + character * 64


def release() -> ProductionReleaseManifest:
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


def command() -> VenueSubmissionCommand:
    value = bundle()
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


def test_fixture_venue_conformance_binds_exact_release_policy_and_orders() -> None:
    value = command()

    report = verify_venue_conformance(
        release(),
        profile(),
        bundle(),
        value,
        acknowledgements(value),
        now=NOW + timedelta(seconds=2),
    )

    assert report.command_digest == digest_canonical(value)
    assert report.acknowledged_order_ids == value.client_order_ids
    assert report.outcome == "CONFORMANT"


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
            acknowledgements(value),
            now=NOW + timedelta(seconds=2),
        )


def test_venue_conformance_rejects_duplicate_or_wrong_acknowledgement() -> None:
    value = command()
    repeated = (*acknowledgements(value), acknowledgements(value)[0])

    with pytest.raises(VenueConformanceError, match="acknowledgements"):
        verify_venue_conformance(
            release(), profile(), bundle(), value, repeated, now=NOW + timedelta(seconds=2)
        )


def test_venue_cli_verifies_recorded_fixture_without_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    value = command()
    input_path = tmp_path / "venue.json"
    input_path.write_text(
        VenueConformanceInput(
            release=release(),
            profile=profile(),
            order_bundle=bundle(),
            command=value,
            acknowledgements=acknowledgements(value),
            now=NOW + timedelta(seconds=2),
        ).model_dump_json(),
        encoding="utf-8",
    )

    assert main(["venue", "verify", str(input_path)]) == 0
    assert '"outcome": "CONFORMANT"' in capsys.readouterr().out
