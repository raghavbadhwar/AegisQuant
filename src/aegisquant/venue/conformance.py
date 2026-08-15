"""Verify provider-agnostic safety invariants against recorded venue fixtures."""

from __future__ import annotations

from datetime import datetime

from aegisquant.contracts.common import require_utc
from aegisquant.contracts.release import ProductionReleaseManifest
from aegisquant.contracts.risk import OrderBundle, RiskDecisionPayload, TradingEnvironment
from aegisquant.contracts.venue import (
    VenueAdapterProfile,
    VenueConformanceReport,
    VenueOrderLifecycleEvidence,
    VenueRiskAuthorization,
    VenueSubmissionCommand,
)
from aegisquant.security.digests import digest_canonical
from aegisquant.security.risk_signing import (
    ExecutionAuthorizationGate,
    InMemoryDecisionConsumptionStore,
    RiskDecisionVerifier,
    RiskVerificationContext,
    RiskVerificationError,
    TrustedRiskKey,
)


class VenueConformanceError(ValueError):
    pass


def _risk_context(authorization: VenueRiskAuthorization) -> RiskVerificationContext:
    context = authorization.context
    return RiskVerificationContext(
        tenant_id=context.tenant_id,
        environment=str(context.environment),
        legal_entity_id=context.legal_entity_id,
        account_id=context.account_id,
        broker_id=context.broker_id,
        strategy_id=context.strategy_id,
        policy_epoch=context.policy_epoch,
        kill_switch_epoch=context.kill_switch_epoch,
        portfolio_state_sequence=context.portfolio_state_sequence,
        input_manifest_digest=context.input_manifest_digest,
        portfolio_snapshot_digest=context.portfolio_snapshot_digest,
        open_orders_snapshot_digest=context.open_orders_snapshot_digest,
        market_data_snapshot_digest=context.market_data_snapshot_digest,
        reference_data_snapshot_digest=context.reference_data_snapshot_digest,
        fx_snapshot_digest=context.fx_snapshot_digest,
        model_validation_manifest_digest=context.model_validation_manifest_digest,
    )


def _authorize_fixture(
    authorization: VenueRiskAuthorization,
    bundle: OrderBundle,
    trusted_risk_keys: dict[str, TrustedRiskKey],
    *,
    now: datetime,
) -> RiskDecisionPayload:
    try:
        verifier = RiskDecisionVerifier(trusted_risk_keys)
        gate = ExecutionAuthorizationGate(verifier, InMemoryDecisionConsumptionStore())
        payload = gate.authorize_once(
            authorization.decision, bundle, _risk_context(authorization), now=now
        )
        try:
            gate.authorize_once(
                authorization.decision, bundle, _risk_context(authorization), now=now
            )
        except RiskVerificationError:
            return payload
    except (RiskVerificationError, ValueError) as exc:
        raise VenueConformanceError("venue risk authorization is invalid") from exc
    raise VenueConformanceError("venue risk authorization nonce was not consumed")


def verify_venue_conformance(
    release: ProductionReleaseManifest,
    profile: VenueAdapterProfile,
    bundle: OrderBundle,
    command: VenueSubmissionCommand,
    *,
    risk_authorization: VenueRiskAuthorization | None = None,
    trusted_risk_keys: dict[str, TrustedRiskKey] | None = None,
    lifecycles: tuple[VenueOrderLifecycleEvidence, ...] = (),
    now: datetime,
) -> VenueConformanceReport:
    """Validate fixtures only; this function has no network or order-submission capability."""

    now = require_utc(now)
    if bundle.environment is not TradingEnvironment.PAPER:
        raise VenueConformanceError("venue conformance accepts PAPER fixtures only")
    if risk_authorization is None or trusted_risk_keys is None:
        raise VenueConformanceError("venue risk authorization is required")
    payload = _authorize_fixture(risk_authorization, bundle, trusted_risk_keys, now=now)
    if (
        command.risk_decision_digest != digest_canonical(risk_authorization.decision)
        or command.risk_nonce != payload.nonce
        or payload.policy_bundle_digest != release.risk_policy_digest
        or payload.model_validation_manifest_digest != release.model_validation_manifest_digest
    ):
        raise VenueConformanceError("venue command risk authorization is mismatched")
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
    if len(lifecycles) != len(command.client_order_ids):
        raise VenueConformanceError("venue lifecycle evidence must cover every order exactly once")
    seen_venue_ids: set[str] = set()
    acknowledgement_digests: list[str] = []
    for client_order_id, lifecycle in zip(command.client_order_ids, lifecycles, strict=True):
        acknowledgement = lifecycle.retry_acknowledgement
        timeout_seconds = (lifecycle.timeout_at - lifecycle.first_attempt_at).total_seconds()
        if (
            lifecycle.client_order_id != client_order_id
            or lifecycle.first_attempt_at < command.not_before
            or lifecycle.timeout_at >= command.expires_at
            or timeout_seconds <= 0
            or timeout_seconds > profile.max_submission_timeout_seconds
            or acknowledgement.tenant_id != command.tenant_id
            or acknowledgement.account_id != command.account_id
            or acknowledgement.broker_id != command.broker_id
            or acknowledgement.command_digest != command_digest
            or acknowledgement.client_order_id != client_order_id
            or acknowledgement.status != "ACCEPTED"
            or acknowledgement.venue_order_id in seen_venue_ids
            or acknowledgement.observed_at < lifecycle.timeout_at
            or acknowledgement.observed_at >= command.expires_at
            or acknowledgement.observed_at > now
            or lifecycle.status_venue_order_id != acknowledgement.venue_order_id
            or lifecycle.status_observed_at < acknowledgement.observed_at
            or lifecycle.status_observed_at >= command.expires_at
            or lifecycle.status_observed_at > now
            or lifecycle.cancellation_venue_order_id != acknowledgement.venue_order_id
            or lifecycle.cancelled_at < lifecycle.status_observed_at
            or lifecycle.cancelled_at >= command.expires_at
            or lifecycle.cancelled_at > now
        ):
            raise VenueConformanceError(
                "venue lifecycle evidence is outside the exact command scope"
            )
        seen_venue_ids.add(acknowledgement.venue_order_id)
        acknowledgement_digests.append(digest_canonical(acknowledgement))
    report_data = {
        "tenant_id": command.tenant_id,
        "broker_id": command.broker_id,
        "command_digest": command_digest,
        "acknowledged_order_ids": command.client_order_ids,
        "lifecycle_digests": tuple(digest_canonical(item) for item in lifecycles),
        "retry_acknowledgement_digests": tuple(acknowledgement_digests),
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
