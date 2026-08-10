"""Offline, candidate-only investor-response contracts with explicit abstention."""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Literal, Protocol

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel


class InvestorArchetype(StrEnum):
    """Named candidate investor archetypes; none carries decision authority."""

    FUNDAMENTAL_LONG_ONLY = "fundamental_long_only"
    FUNDAMENTAL_LONG_SHORT = "fundamental_long_short"
    SYSTEMATIC_FACTOR = "systematic_factor"
    TREND_FOLLOWER = "trend_follower"
    PASSIVE_INDEX = "passive_index"
    RETAIL_ATTENTION = "retail_attention"
    OPTIONS_SPECULATIVE = "options_speculative"
    MARKET_MAKER_DEALER = "market_maker_dealer"
    LEVERAGED_FORCED_SELLER = "leveraged_forced_seller"


class MarketResponseStatus(StrEnum):
    """A candidate response or a typed refusal to produce one."""

    CANDIDATE_RESPONSE = "candidate_response"
    ABSTAINED = "abstained"


class InvestorArchetypeState(CandidateContractModel):
    """Bounded uncalibrated inputs for one candidate response archetype."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    archetype_id: str = Field(min_length=1)
    archetype: InvestorArchetype
    capital_share: float = Field(ge=0.0, le=1.0)
    information_set: tuple[str, ...] = Field(min_length=1)
    horizon_days: int = Field(ge=1)
    risk_budget: float = Field(ge=0.0)
    leverage: float = Field(ge=0.0)
    liquidity_need: float = Field(ge=0.0, le=1.0)
    current_positioning: float = Field(ge=-1.0, le=1.0)
    demand_sensitivity: float = Field(ge=-1.0, le=1.0)
    continuation_probability: float = Field(ge=0.0, le=1.0)
    reversal_probability: float = Field(ge=0.0, le=1.0)
    volatility_sensitivity: float = Field(ge=-1.0, le=1.0)
    liquidity_sensitivity: float = Field(ge=-1.0, le=1.0)
    calibration_status: Literal["not_calibrated"] = "not_calibrated"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_bounded_candidate_input(self) -> InvestorArchetypeState:
        values = (
            self.capital_share,
            self.risk_budget,
            self.leverage,
            self.liquidity_need,
            self.current_positioning,
            self.demand_sensitivity,
            self.continuation_probability,
            self.reversal_probability,
            self.volatility_sensitivity,
            self.liquidity_sensitivity,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("investor archetype state values must be finite")
        if any(not item for item in self.information_set) or len(self.information_set) != len(
            set(self.information_set)
        ):
            raise ValueError("investor archetype information set must be nonempty and unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("investor archetype state content hash mismatch")
        return self

    def sealed(self) -> InvestorArchetypeState:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = InvestorArchetypeState.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class MarketResponseRequest(CandidateContractModel):
    """One sealed no-I/O request for an explicitly uncalibrated response calculation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    scenario_run_id: str = Field(min_length=1)
    scenario_run_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: AwareDatetime
    regime_id: str = Field(min_length=1)
    candidate_event_signal: float = Field(ge=-1.0, le=1.0)
    archetype_state: InvestorArchetypeState
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def binds_sealed_candidate_inputs(self) -> MarketResponseRequest:
        state = InvestorArchetypeState.model_validate(self.archetype_state.model_dump(mode="json"))
        if state.content_hash is None:
            raise ValueError("market response request requires a sealed archetype state")
        if not isfinite(self.candidate_event_signal):
            raise ValueError("market response request signal must be finite")
        if any(not item for item in self.assumption_ids) or len(self.assumption_ids) != len(
            set(self.assumption_ids)
        ):
            raise ValueError("market response request assumption IDs must be nonempty and unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("market response request content hash mismatch")
        return self

    def sealed(self) -> MarketResponseRequest:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = MarketResponseRequest.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


SUPPORTED_ARCHETYPES = frozenset(
    {InvestorArchetype.FUNDAMENTAL_LONG_ONLY, InvestorArchetype.SYSTEMATIC_FACTOR}
)
SUPPORTED_REGIMES = frozenset({"normal", "stress"})


def _candidate_metrics(
    request: MarketResponseRequest,
) -> tuple[float, int, float, float, float, float]:
    state = request.archetype_state
    intensity = request.candidate_event_signal * state.capital_share
    return (
        intensity * state.demand_sensitivity * (1.0 - abs(state.current_positioning)),
        state.horizon_days,
        state.continuation_probability,
        state.reversal_probability,
        abs(request.candidate_event_signal) * state.volatility_sensitivity,
        abs(request.candidate_event_signal) * state.liquidity_sensitivity,
    )


class MarketResponseOutcome(CandidateContractModel):
    """Sealed offline response or abstention; it contains neither prices nor decisions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: MarketResponseRequest
    adapter_id: Literal["deterministic-archetype-v1"] = "deterministic-archetype-v1"
    status: MarketResponseStatus
    expected_demand_imbalance: float | None = None
    flow_timing_days: int | None = None
    continuation_probability: float | None = None
    reversal_probability: float | None = None
    volatility_change: float | None = None
    liquidity_change: float | None = None
    narrative_feedback: tuple[str, ...] = ()
    reason: Literal["unsupported_archetype", "unsupported_regime"] | None = None
    calibration_status: Literal["not_calibrated"] = "not_calibrated"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_exactly_reconciled_or_explicitly_abstained(self) -> MarketResponseOutcome:
        request = MarketResponseRequest.model_validate(self.request.model_dump(mode="json"))
        if request.content_hash is None:
            raise ValueError("market response outcome requires a sealed request")
        supported_archetype = request.archetype_state.archetype in SUPPORTED_ARCHETYPES
        supported_regime = request.regime_id in SUPPORTED_REGIMES
        values = (
            self.expected_demand_imbalance,
            self.flow_timing_days,
            self.continuation_probability,
            self.reversal_probability,
            self.volatility_change,
            self.liquidity_change,
        )
        if self.status == MarketResponseStatus.ABSTAINED:
            expected_reason = (
                "unsupported_archetype" if not supported_archetype else "unsupported_regime"
            )
            if supported_archetype and supported_regime:
                raise ValueError("market response cannot abstain for a supported request")
            if self.reason != expected_reason or any(value is not None for value in values):
                raise ValueError(
                    "market response abstention must retain its exact unsupported reason"
                )
            if self.narrative_feedback:
                raise ValueError("market response abstention cannot provide narrative feedback")
        else:
            if not supported_archetype or not supported_regime:
                raise ValueError("market response must abstain for unsupported inputs")
            if self.reason is not None or any(value is None for value in values):
                raise ValueError("candidate market response requires all deterministic values")
            expected = _candidate_metrics(request)
            if values != expected:
                raise ValueError(
                    "candidate market response values do not reconcile to sealed inputs"
                )
            if self.narrative_feedback != ("deterministic_candidate_response",):
                raise ValueError("candidate market response feedback must be deterministic")
        expected_hash = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected_hash:
            raise ValueError("market response outcome content hash mismatch")
        return self

    def sealed(self) -> MarketResponseOutcome:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = MarketResponseOutcome.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class InvestorResponseAdapter(Protocol):
    """An optional offline adapter; its result has no decision authority."""

    def respond(self, request: MarketResponseRequest) -> MarketResponseOutcome: ...


class DeterministicInvestorResponseAdapter:
    """One bounded pure-Python adapter for supported candidate archetypes/regimes."""

    def respond(self, request: MarketResponseRequest) -> MarketResponseOutcome:
        validated = MarketResponseRequest.model_validate(request.model_dump(mode="json"))
        if validated.content_hash is None:
            raise ValueError("deterministic response adapter requires a sealed request")
        state = validated.archetype_state
        if state.archetype not in SUPPORTED_ARCHETYPES:
            return MarketResponseOutcome(
                request=validated,
                status=MarketResponseStatus.ABSTAINED,
                reason="unsupported_archetype",
            ).sealed()
        if validated.regime_id not in SUPPORTED_REGIMES:
            return MarketResponseOutcome(
                request=validated,
                status=MarketResponseStatus.ABSTAINED,
                reason="unsupported_regime",
            ).sealed()
        (
            expected_demand_imbalance,
            flow_timing_days,
            continuation_probability,
            reversal_probability,
            volatility_change,
            liquidity_change,
        ) = _candidate_metrics(validated)
        return MarketResponseOutcome(
            request=validated,
            status=MarketResponseStatus.CANDIDATE_RESPONSE,
            expected_demand_imbalance=expected_demand_imbalance,
            flow_timing_days=flow_timing_days,
            continuation_probability=continuation_probability,
            reversal_probability=reversal_probability,
            volatility_change=volatility_change,
            liquidity_change=liquidity_change,
            narrative_feedback=("deterministic_candidate_response",),
        ).sealed()
