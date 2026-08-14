"""Verify provider-agnostic safety invariants against recorded venue fixtures."""

from __future__ import annotations

from datetime import datetime

from aegisquant.contracts.common import require_utc
from aegisquant.contracts.release import ProductionReleaseManifest
from aegisquant.contracts.risk import OrderBundle, TradingEnvironment
from aegisquant.contracts.venue import (
    VenueAdapterProfile,
    VenueConformanceReport,
    VenueOrderAcknowledgement,
    VenueSubmissionCommand,
)
from aegisquant.security.digests import digest_canonical


class VenueConformanceError(ValueError):
    pass


def verify_venue_conformance(
    release: ProductionReleaseManifest,
    profile: VenueAdapterProfile,
    bundle: OrderBundle,
    command: VenueSubmissionCommand,
    acknowledgements: tuple[VenueOrderAcknowledgement, ...],
    *,
    now: datetime,
) -> VenueConformanceReport:
    """Validate fixtures only; this function has no network or order-submission capability."""

    now = require_utc(now)
    if bundle.environment is not TradingEnvironment.PAPER:
        raise VenueConformanceError("venue conformance accepts PAPER fixtures only")
    if now < release.created_at or now >= release.expires_at:
        raise VenueConformanceError("release manifest is not current")
    if now < profile.reviewed_at or now >= profile.expires_at:
        raise VenueConformanceError("venue profile is not current")
    if now < command.not_before or now >= command.expires_at:
        raise VenueConformanceError("venue command is not current")
    if (
        profile.broker_id != release.broker_id
        or profile.broker_id != bundle.broker_id
        or command.broker_id != release.broker_id
        or command.tenant_id != release.tenant_id
        or command.tenant_id != bundle.tenant_id
        or command.account_id != release.account_id
        or command.account_id != bundle.account_id
        or command.legal_entity_id != release.legal_entity_id
        or command.legal_entity_id != bundle.legal_entity_id
        or command.release_manifest_digest != digest_canonical(release)
    ):
        raise VenueConformanceError("venue command is outside the release scope")
    if (
        profile.compliance_policy_pack_id != release.compliance_policy_pack_id
        or profile.compliance_policy_pack_digest != release.compliance_policy_pack_digest
        or command.compliance_policy_pack_id != release.compliance_policy_pack_id
        or command.compliance_policy_pack_digest != release.compliance_policy_pack_digest
    ):
        raise VenueConformanceError("venue command policy pack is mismatched")
    if (
        command.submission_hostname not in release.broker_api_hostnames
        or command.submission_hostname not in profile.allowed_hostnames
    ):
        raise VenueConformanceError("venue command hostname is not allowlisted")
    if (
        command.request_id != bundle.request_id
        or command.order_bundle_digest != digest_canonical(bundle)
        or command.client_order_ids != tuple(order.client_order_id for order in bundle.orders)
    ):
        raise VenueConformanceError("venue command order IDs or bundle are mismatched")
    if any(order.order_type not in profile.supported_order_types for order in bundle.orders):
        raise VenueConformanceError("venue profile does not support every authorized order type")
    command_digest = digest_canonical(command)
    if len(acknowledgements) != len(command.client_order_ids):
        raise VenueConformanceError("venue acknowledgements must cover every order exactly once")
    seen_client_ids: set[str] = set()
    seen_venue_ids: set[str] = set()
    for acknowledgement in acknowledgements:
        if (
            acknowledgement.tenant_id != command.tenant_id
            or acknowledgement.account_id != command.account_id
            or acknowledgement.broker_id != command.broker_id
            or acknowledgement.command_digest != command_digest
            or acknowledgement.client_order_id not in command.client_order_ids
            or acknowledgement.client_order_id in seen_client_ids
            or acknowledgement.venue_order_id in seen_venue_ids
            or acknowledgement.observed_at < command.not_before
            or acknowledgement.observed_at >= command.expires_at
        ):
            raise VenueConformanceError(
                "venue acknowledgements are outside the exact command scope"
            )
        seen_client_ids.add(acknowledgement.client_order_id)
        seen_venue_ids.add(acknowledgement.venue_order_id)
    if (
        tuple(acknowledgement.client_order_id for acknowledgement in acknowledgements)
        != command.client_order_ids
    ):
        raise VenueConformanceError(
            "venue acknowledgements are not ordered by the submitted command"
        )
    report_data = {
        "tenant_id": command.tenant_id,
        "broker_id": command.broker_id,
        "command_digest": command_digest,
        "acknowledged_order_ids": command.client_order_ids,
        "acknowledgement_digests": tuple(digest_canonical(item) for item in acknowledgements),
        "verified_at": now,
    }
    return VenueConformanceReport(
        tenant_id=command.tenant_id,
        broker_id=command.broker_id,
        command_digest=command_digest,
        acknowledged_order_ids=command.client_order_ids,
        report_digest=digest_canonical(report_data),
        verified_at=now,
    )
