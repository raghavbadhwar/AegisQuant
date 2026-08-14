"""One deterministic offline research-to-paper fixture path."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import Field, field_validator, model_validator

from aegisquant.case_ledger.store import InMemoryCaseEventStore
from aegisquant.contracts.common import FixedDecimal, Identifier, Nonce, Sha256Digest, StrictModel
from aegisquant.contracts.research import (
    DataSnapshot,
    MarketBar,
    PaperFill,
    PerformanceReport,
    ResearchManifest,
    SecurityVersion,
)
from aegisquant.contracts.risk import (
    DecisionOutcome,
    OrderBundle,
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecisionPayload,
    TimeInForce,
    TradingEnvironment,
)
from aegisquant.quant.metrics import performance_report
from aegisquant.quant.paper import (
    DeterministicPaperVenue,
    PaperAccountState,
    reconcile_execution,
)
from aegisquant.quant.pit import marked_nav, next_market_bar
from aegisquant.quant.portfolio import (
    Forecast,
    PortfolioPolicy,
    PortfolioTarget,
    blend_forecasts,
    build_long_only_target,
)
from aegisquant.quant.risk import RiskPolicy, evaluate_policy, policy_allows
from aegisquant.quant.timeline import ExecutionTimeline
from aegisquant.security.digests import digest_canonical
from aegisquant.security.risk_signing import (
    ExecutionAuthorizationGate,
    InMemoryDecisionConsumptionStore,
    RiskDecisionSigner,
    RiskDecisionVerifier,
    RiskVerificationContext,
    TrustedRiskKey,
)


class FixtureCaseError(ValueError):
    pass


class FixtureCaseSpec(StrictModel):
    schema_version: Literal[1] = 1
    manifest: ResearchManifest
    snapshot: DataSnapshot
    forecasts: tuple[Forecast, ...] = Field(min_length=1)
    bars: tuple[MarketBar, ...] = Field(min_length=2)
    securities: tuple[SecurityVersion, ...] = Field(min_length=1)
    portfolio_policy: PortfolioPolicy
    risk_policy: RiskPolicy
    initial_cash: FixedDecimal
    annualization_periods: int = Field(default=252, ge=1)

    @field_validator("snapshot", mode="before")
    @classmethod
    def parse_snapshot(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        for field in ("as_of", "frozen_at"):
            if isinstance(data.get(field), str):
                data[field] = datetime.fromisoformat(data[field].replace("Z", "+00:00"))
        if isinstance(data.get("case_id"), str):
            data["case_id"] = UUID(data["case_id"])
        return DataSnapshot.model_validate(data)

    @field_validator("forecasts", mode="before")
    @classmethod
    def parse_forecasts(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        parsed: list[Forecast] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("forecasts must be JSON objects")
            data = dict(item)
            provenance = data.get("feature_provenance")
            if isinstance(provenance, list):
                data["feature_provenance"] = tuple(provenance)
            parsed.append(Forecast.model_validate(data))
        return tuple(parsed)

    @field_validator("bars", mode="before")
    @classmethod
    def parse_bars(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        parsed: list[MarketBar] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("bars must be JSON objects")
            data = dict(item)
            for field in ("observed_at", "available_at", "tradable_at"):
                if isinstance(data.get(field), str):
                    data[field] = datetime.fromisoformat(data[field].replace("Z", "+00:00"))
            parsed.append(MarketBar.model_validate(data))
        return tuple(parsed)

    @field_validator("securities", mode="before")
    @classmethod
    def parse_securities(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        parsed: list[SecurityVersion] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("securities must be JSON objects")
            data = dict(item)
            for field in ("valid_from", "valid_until"):
                if isinstance(data.get(field), str):
                    data[field] = datetime.fromisoformat(data[field].replace("Z", "+00:00"))
            parsed.append(SecurityVersion.model_validate(data))
        return tuple(parsed)

    @field_validator("initial_cash")
    @classmethod
    def positive_cash(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("initial_cash must be positive")
        return value

    @model_validator(mode="after")
    def inputs_are_bound(self) -> FixtureCaseSpec:
        if (
            self.snapshot.tenant_id != self.manifest.tenant_id
            or self.snapshot.case_id != self.manifest.case_id
            or self.snapshot.snapshot_id != self.manifest.snapshot_id
            or self.snapshot.manifest_digest != self.manifest.snapshot_manifest_digest
            or self.snapshot.content_digest != self.manifest.snapshot_content_digest
            or self.snapshot.frozen_at != self.manifest.frozen_at
        ):
            raise ValueError("fixture snapshot must exactly bind the research manifest")
        if self.snapshot.content_digest != digest_canonical(
            {"bars": self.bars, "securities": self.securities, "forecasts": self.forecasts}
        ):
            raise ValueError("fixture snapshot content digest does not bind frozen inputs")
        securities = {item.instrument_id: item for item in self.securities}
        if len(securities) != len(self.securities):
            raise ValueError("fixture securities must have unique instrument IDs")
        forecast_ids = {item.instrument_id for item in self.forecasts}
        if forecast_ids - securities.keys():
            raise ValueError("every forecast requires a matching security")
        for instrument_id in forecast_ids:
            horizons = {
                item.horizon_days for item in self.forecasts if item.instrument_id == instrument_id
            }
            if len(horizons) != 1:
                raise ValueError("forecasts for one instrument must share one horizon")
        if any(not item.feature_provenance for item in self.forecasts):
            raise ValueError("fixture forecasts require explicit feature provenance")
        required_data_digests = {
            digest_canonical(self.bars),
            digest_canonical(self.securities),
        }
        if not required_data_digests.issubset(self.manifest.data_manifest_digests):
            raise ValueError("fixture bars and securities must be bound by data manifests")
        if digest_canonical(self.forecasts) not in self.manifest.model_fixture_digests:
            raise ValueError("fixture forecasts must be bound by a model fixture manifest")
        for market_bar in self.bars:
            security = securities.get(market_bar.instrument_id)
            if security is None or security.instrument_version != market_bar.instrument_version:
                raise ValueError("every market bar requires a matching security version")
            if market_bar.currency != "USD":
                raise ValueError("the M0 fixture runner supports USD bars only")
        decision_at = self.manifest.frozen_at
        for instrument_id in forecast_ids:
            instrument_bars = tuple(
                item for item in self.bars if item.instrument_id == instrument_id
            )
            if not any(item.available_at < decision_at for item in instrument_bars):
                raise ValueError("every forecast requires a pre-decision market bar")
            if not any(
                item.available_at > decision_at and item.tradable_at > decision_at
                for item in instrument_bars
            ):
                raise ValueError("every forecast requires a post-decision fill bar")
        return self


class FixtureCaseReport(StrictModel):
    schema_version: Literal[1] = 1
    mode: Literal["OFFLINE_FIXTURE_PAPER"] = "OFFLINE_FIXTURE_PAPER"
    tenant_id: Identifier
    case_id: UUID
    manifest_digest: Sha256Digest
    portfolio_target: PortfolioTarget
    portfolio_target_digest: Sha256Digest
    risk_decision_nonce: Nonce
    risk_decision_digest: Sha256Digest
    execution_digest: Sha256Digest
    fills: tuple[PaperFill, ...]
    final_account: PaperAccountState
    final_nav: FixedDecimal
    reconciled: Literal[True]
    ledger_verified: Literal[True]
    ledger_event_count: int = Field(ge=1)
    ledger_event_types: tuple[str, ...]
    performance: PerformanceReport

    @field_validator("fills", "ledger_event_types", mode="before")
    @classmethod
    def parse_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


def _current_bars(spec: FixtureCaseSpec) -> dict[str, MarketBar]:
    decision_at = spec.manifest.frozen_at
    instrument_ids = {item.instrument_id for item in spec.forecasts}
    return {
        instrument_id: max(
            (
                item
                for item in spec.bars
                if item.instrument_id == instrument_id and item.available_at < decision_at
            ),
            key=lambda item: (item.available_at, item.observed_at),
        )
        for instrument_id in instrument_ids
    }


def _portfolio_target(spec: FixtureCaseSpec) -> PortfolioTarget:
    grouped: defaultdict[str, list[Forecast]] = defaultdict(list)
    for forecast in spec.forecasts:
        grouped[forecast.instrument_id].append(forecast)
    blended = tuple(
        blend_forecasts(
            tuple(grouped[instrument_id]),
            uncertainty_floor=spec.portfolio_policy.uncertainty_floor,
        )
        for instrument_id in sorted(grouped)
    )
    target = build_long_only_target(blended, policy=spec.portfolio_policy)
    if not target.weights:
        raise FixtureCaseError("fixture forecasts produced no executable long exposure")
    return target


def run_fixture_case(spec: FixtureCaseSpec) -> FixtureCaseReport:
    manifest_digest = digest_canonical(spec.manifest)
    target = _portfolio_target(spec)
    target_digest = digest_canonical(target)
    decision_at = spec.manifest.frozen_at
    current_bars = _current_bars(spec)
    securities = {item.instrument_id: item for item in spec.securities}
    orders = tuple(
        OrderIntent(
            client_order_id=f"fixture-order-{index}",
            instrument_id=item.instrument_id,
            instrument_version=securities[item.instrument_id].instrument_version,
            venue_id="fixture-venue",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            quantity=spec.initial_cash * item.weight / current_bars[item.instrument_id].close_price,
            currency="USD",
        )
        for index, item in enumerate(target.weights, start=1)
    )
    case_key = f"{spec.manifest.case_id}:{manifest_digest}"
    bundle = OrderBundle(
        tenant_id=spec.manifest.tenant_id,
        environment=TradingEnvironment.PAPER,
        legal_entity_id="fixture-entity",
        account_id="fixture-paper-account",
        broker_id="local-paper-venue",
        strategy_id="fixture-multi-asset-control",
        case_id=spec.manifest.case_id,
        request_id=uuid5(NAMESPACE_URL, f"aegisquant:request:{case_key}"),
        portfolio_state_sequence=0,
        orders=orders,
    )
    account = PaperAccountState(
        tenant_id=bundle.tenant_id,
        case_id=bundle.case_id,
        account_id=bundle.account_id,
        cash=spec.initial_cash,
        positions=(),
        state_sequence=0,
    )
    rule_results = evaluate_policy(
        bundle,
        positions=account.positions,
        bars=current_bars,
        securities=securities,
        cash=account.cash,
        policy=spec.risk_policy,
        as_of=decision_at,
    )
    if not policy_allows(rule_results):
        raise FixtureCaseError("fixture order bundle failed its risk policy")

    bundle_digest = digest_canonical(bundle)
    portfolio_snapshot_digest = digest_canonical(account)
    open_orders_snapshot_digest = digest_canonical(())
    market_data_snapshot_digest = digest_canonical(
        tuple(current_bars[item] for item in sorted(current_bars))
    )
    reference_data_snapshot_digest = digest_canonical(
        tuple(securities[item] for item in sorted(securities))
    )
    fx_snapshot_digest = digest_canonical({"USD": Decimal(1)})
    model_validation_manifest_digest = digest_canonical(spec.forecasts)
    next_bars = {
        item.instrument_id: next_market_bar(
            spec.bars, instrument_id=item.instrument_id, after=decision_at
        )
        for item in target.weights
    }
    fill_times = {item.tradable_at for item in next_bars.values()}
    if len(fill_times) != 1:
        raise FixtureCaseError("all fixture orders must share one deterministic fill time")
    timeline = ExecutionTimeline(
        information_cutoff=max(item.available_at for item in current_bars.values()),
        decision_at=decision_at,
        order_submitted_at=decision_at,
        fill_at=fill_times.pop(),
    )
    context = RiskVerificationContext(
        tenant_id=bundle.tenant_id,
        environment=str(bundle.environment),
        legal_entity_id=bundle.legal_entity_id,
        account_id=bundle.account_id,
        broker_id=bundle.broker_id,
        strategy_id=bundle.strategy_id,
        policy_epoch=1,
        kill_switch_epoch=0,
        portfolio_state_sequence=bundle.portfolio_state_sequence,
        input_manifest_digest=manifest_digest,
        portfolio_snapshot_digest=portfolio_snapshot_digest,
        open_orders_snapshot_digest=open_orders_snapshot_digest,
        market_data_snapshot_digest=market_data_snapshot_digest,
        reference_data_snapshot_digest=reference_data_snapshot_digest,
        fx_snapshot_digest=fx_snapshot_digest,
        model_validation_manifest_digest=model_validation_manifest_digest,
    )
    payload = RiskDecisionPayload(
        tenant_id=bundle.tenant_id,
        decision_id=uuid5(NAMESPACE_URL, f"aegisquant:risk-decision:{case_key}"),
        request_id=bundle.request_id,
        case_id=bundle.case_id,
        issuance_sequence=1,
        nonce=hashlib.sha256(f"aegisquant:nonce:{case_key}".encode()).hexdigest()[:32],
        environment=bundle.environment,
        legal_entity_id=bundle.legal_entity_id,
        account_id=bundle.account_id,
        broker_id=bundle.broker_id,
        strategy_id=bundle.strategy_id,
        outcome=DecisionOutcome.APPROVE,
        policy_bundle_digest=digest_canonical(spec.risk_policy),
        policy_epoch=context.policy_epoch,
        kill_switch_epoch=context.kill_switch_epoch,
        input_manifest_digest=context.input_manifest_digest,
        portfolio_state_sequence=context.portfolio_state_sequence,
        portfolio_snapshot_digest=context.portfolio_snapshot_digest,
        open_orders_snapshot_digest=context.open_orders_snapshot_digest,
        market_data_snapshot_digest=context.market_data_snapshot_digest,
        reference_data_snapshot_digest=context.reference_data_snapshot_digest,
        fx_snapshot_digest=context.fx_snapshot_digest,
        model_validation_manifest_digest=context.model_validation_manifest_digest,
        execution_plan_digest=digest_canonical(
            {
                "bars": spec.bars,
                "timeline": timeline,
                "transaction_cost_rate": Decimal("0.0005"),
            }
        ),
        requested_order_bundle_digest=bundle_digest,
        approved_order_bundle_digest=bundle_digest,
        projected_portfolio_digest=target_digest,
        rule_results=rule_results,
        created_at=decision_at,
        not_before=decision_at,
        expires_at=decision_at + timedelta(minutes=5),
    )
    fixture_key = Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(b"aegisquant-offline-fixture-risk-key-v1").digest()
    )
    signed = RiskDecisionSigner("fixture-risk-key-v1", fixture_key).sign(payload)
    gate = ExecutionAuthorizationGate(
        RiskDecisionVerifier(
            {
                "fixture-risk-key-v1": TrustedRiskKey(
                    public_key=fixture_key.public_key(),
                    valid_from=decision_at - timedelta(days=1),
                    valid_until=decision_at + timedelta(days=1),
                )
            }
        ),
        InMemoryDecisionConsumptionStore(),
    )
    execution = DeterministicPaperVenue(authorization_gate=gate).execute(
        bundle,
        signed_decision=signed,
        verification_context=context,
        account=account,
        bars=spec.bars,
        securities=securities,
        policy=spec.risk_policy,
        timeline=timeline,
        as_of=decision_at,
    )
    if not reconcile_execution(account, execution):
        raise FixtureCaseError("paper execution failed independent reconciliation")
    quantities = {item.instrument_id: item.quantity for item in execution.account.positions}
    marks = {item.instrument_id: item.mark_price for item in execution.account.positions}
    final_nav = marked_nav(execution.account.cash, quantities, marks)
    performance = performance_report(
        (final_nav / spec.initial_cash - Decimal(1),),
        annualization_periods=spec.annualization_periods,
    )

    ledger = InMemoryCaseEventStore()
    correlation_id = uuid5(NAMESPACE_URL, f"aegisquant:correlation:{case_key}")
    event_specs: tuple[tuple[str, datetime, dict[str, Any]], ...] = (
        ("RESEARCH_MANIFEST_VERIFIED", decision_at, {"manifest_digest": manifest_digest}),
        ("PORTFOLIO_TARGET_BUILT", decision_at, {"target_digest": target_digest}),
        ("RISK_DECISION_SIGNED", decision_at, {"decision_digest": digest_canonical(signed)}),
        (
            "PAPER_EXECUTION_RECORDED",
            timeline.fill_at,
            {"execution_digest": execution.execution_digest},
        ),
        ("EXECUTION_RECONCILED", timeline.fill_at, {"reconciled": True}),
        (
            "PERFORMANCE_REPORT_EMITTED",
            timeline.fill_at,
            {"performance_digest": digest_canonical(performance)},
        ),
    )
    causation_id = None
    for index, (event_type, occurred_at, event_payload) in enumerate(event_specs, start=1):
        event = ledger.append(
            tenant_id=spec.manifest.tenant_id,
            case_id=spec.manifest.case_id,
            event_type=event_type,
            occurred_at=occurred_at,
            recorded_at=occurred_at,
            actor_id="offline-fixture-runner",
            correlation_id=correlation_id,
            causation_id=causation_id,
            idempotency_key=f"{spec.manifest.case_id}:fixture-stage-{index}",
            payload=event_payload,
        )
        causation_id = event.event_id
    events = ledger.read(tenant_id=spec.manifest.tenant_id, case_id=spec.manifest.case_id)
    if not ledger.verify_chain(tenant_id=spec.manifest.tenant_id, case_id=spec.manifest.case_id):
        raise FixtureCaseError("fixture ledger chain verification failed")
    return FixtureCaseReport(
        tenant_id=spec.manifest.tenant_id,
        case_id=spec.manifest.case_id,
        manifest_digest=manifest_digest,
        portfolio_target=target,
        portfolio_target_digest=target_digest,
        risk_decision_nonce=payload.nonce,
        risk_decision_digest=digest_canonical(signed),
        execution_digest=execution.execution_digest,
        fills=execution.fills,
        final_account=execution.account,
        final_nav=final_nav,
        reconciled=True,
        ledger_verified=True,
        ledger_event_count=len(events),
        ledger_event_types=tuple(item.event_type for item in events),
        performance=performance,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run-fixture-case",
        description="Run one deterministic, offline AegisQuant PAPER fixture.",
    )
    parser.add_argument("fixture", type=Path, help="path to a FixtureCaseSpec JSON file")
    args = parser.parse_args(argv)
    try:
        spec = FixtureCaseSpec.model_validate_json(args.fixture.read_bytes())
        report = run_fixture_case(spec)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"run-fixture-case: {exc}\n")
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
