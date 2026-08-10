"""Isolated offline microstructure research contracts; never an execution path."""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Final, Literal, Protocol

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel

V3_SIMULATED_EXECUTION_BOUNDARY_ID: Final[Literal["aegis-v3-simulated-execution-cost-seam"]] = (
    "aegis-v3-simulated-execution-cost-seam"
)


class MicrostructureStatus(StrEnum):
    """Candidate stress output or an explicit unsupported-condition abstention."""

    CANDIDATE_RESEARCH = "candidate_research"
    ABSTAINED = "abstained"


class MicrostructureScenario(CandidateContractModel):
    """One bounded no-I/O microstructure stress coordinate without order inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(min_length=1)
    as_of: AwareDatetime
    scenario_run_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    regime_id: str = Field(min_length=1)
    liquidity_stress: float = Field(ge=0.0, le=1.0)
    participation_rate: float = Field(ge=0.0, le=1.0)
    latency_stress_ms: int = Field(ge=0, le=60_000)
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    execution_boundary_id: Literal["aegis-v3-simulated-execution-cost-seam"] = (
        V3_SIMULATED_EXECUTION_BOUNDARY_ID
    )
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_bounded_and_isolated(self) -> MicrostructureScenario:
        if not isfinite(self.liquidity_stress) or not isfinite(self.participation_rate):
            raise ValueError("microstructure scenario stress values must be finite")
        if any(not item for item in self.assumption_ids) or len(self.assumption_ids) != len(
            set(self.assumption_ids)
        ):
            raise ValueError("microstructure scenario assumption IDs must be nonempty and unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("microstructure scenario content hash mismatch")
        return self

    def sealed(self) -> MicrostructureScenario:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = MicrostructureScenario.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class MicrostructureAdapterConfig(CandidateContractModel):
    """Bounded uncalibrated parameters for the one deterministic research adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_id: str = Field(min_length=1)
    base_latency_ms: int = Field(ge=0, le=60_000)
    max_candidate_impact_bps: float = Field(ge=0.0, le=10_000.0)
    max_candidate_slippage_bps: float = Field(ge=0.0, le=10_000.0)
    supported_regimes: tuple[Literal["normal", "stress"], ...] = Field(min_length=1)
    calibration_status: Literal["not_calibrated"] = "not_calibrated"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_bounded_and_content_addressed(self) -> MicrostructureAdapterConfig:
        if not isfinite(self.max_candidate_impact_bps) or not isfinite(
            self.max_candidate_slippage_bps
        ):
            raise ValueError("microstructure adapter bounds must be finite")
        if len(self.supported_regimes) != len(set(self.supported_regimes)):
            raise ValueError("microstructure adapter regimes must be unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("microstructure adapter config content hash mismatch")
        return self

    def sealed(self) -> MicrostructureAdapterConfig:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = MicrostructureAdapterConfig.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def _candidate_metrics(
    scenario: MicrostructureScenario, config: MicrostructureAdapterConfig
) -> tuple[float, float, int, float]:
    intensity = scenario.liquidity_stress * scenario.participation_rate
    return (
        config.max_candidate_impact_bps * intensity,
        config.max_candidate_slippage_bps * intensity,
        config.base_latency_ms + scenario.latency_stress_ms,
        1.0 - scenario.liquidity_stress,
    )


class MicrostructureResearchOutcome(CandidateContractModel):
    """A sealed stress observation, not a trading or cost decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario: MicrostructureScenario
    config: MicrostructureAdapterConfig
    adapter_id: Literal["deterministic-microstructure-research-v1"] = (
        "deterministic-microstructure-research-v1"
    )
    execution_boundary_id: Literal["aegis-v3-simulated-execution-cost-seam"] = (
        V3_SIMULATED_EXECUTION_BOUNDARY_ID
    )
    status: MicrostructureStatus
    candidate_impact_bps: float | None = None
    candidate_slippage_stress_bps: float | None = None
    candidate_latency_ms: int | None = None
    candidate_liquidity_score: float | None = None
    reason: Literal["unsupported_regime"] | None = None
    calibration_status: Literal["not_calibrated"] = "not_calibrated"
    research_disposition: Literal["engineering_only"] = "engineering_only"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_exactly_reconciled_or_explicitly_abstained(self) -> MicrostructureResearchOutcome:
        scenario = MicrostructureScenario.model_validate(self.scenario.model_dump(mode="json"))
        config = MicrostructureAdapterConfig.model_validate(self.config.model_dump(mode="json"))
        if scenario.content_hash is None or config.content_hash is None:
            raise ValueError("microstructure outcome requires sealed scenario and config")
        if self.execution_boundary_id != scenario.execution_boundary_id:
            raise ValueError("microstructure outcome must retain the v3 execution boundary")
        values = (
            self.candidate_impact_bps,
            self.candidate_slippage_stress_bps,
            self.candidate_latency_ms,
            self.candidate_liquidity_score,
        )
        if self.status == MicrostructureStatus.ABSTAINED:
            if scenario.regime_id in config.supported_regimes:
                raise ValueError("microstructure adapter cannot abstain for a supported regime")
            if self.reason != "unsupported_regime" or any(value is not None for value in values):
                raise ValueError("microstructure abstention must retain its unsupported reason")
        else:
            if scenario.regime_id not in config.supported_regimes:
                raise ValueError("microstructure adapter must abstain for an unsupported regime")
            if self.reason is not None or any(value is None for value in values):
                raise ValueError("microstructure candidate research requires deterministic values")
            if values != _candidate_metrics(scenario, config):
                raise ValueError(
                    "microstructure candidate values do not reconcile to sealed inputs"
                )
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("microstructure outcome content hash mismatch")
        return self

    def sealed(self) -> MicrostructureResearchOutcome:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = MicrostructureResearchOutcome.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class MicrostructureSimulator(Protocol):
    """Protocol deliberately isolated from orders, brokers, and v3 execution state."""

    def simulate(
        self, scenario: MicrostructureScenario, config: MicrostructureAdapterConfig
    ) -> MicrostructureResearchOutcome: ...


class DeterministicMicrostructureResearchAdapter:
    """Pure offline stress adapter for one permitted bounded research surface."""

    def simulate(
        self, scenario: MicrostructureScenario, config: MicrostructureAdapterConfig
    ) -> MicrostructureResearchOutcome:
        validated_scenario = MicrostructureScenario.model_validate(scenario.model_dump(mode="json"))
        validated_config = MicrostructureAdapterConfig.model_validate(
            config.model_dump(mode="json")
        )
        if validated_scenario.content_hash is None or validated_config.content_hash is None:
            raise ValueError("microstructure research adapter requires sealed inputs")
        if validated_scenario.regime_id not in validated_config.supported_regimes:
            return MicrostructureResearchOutcome(
                scenario=validated_scenario,
                config=validated_config,
                status=MicrostructureStatus.ABSTAINED,
                reason="unsupported_regime",
            ).sealed()
        impact, slippage, latency, liquidity = _candidate_metrics(
            validated_scenario, validated_config
        )
        return MicrostructureResearchOutcome(
            scenario=validated_scenario,
            config=validated_config,
            status=MicrostructureStatus.CANDIDATE_RESEARCH,
            candidate_impact_bps=impact,
            candidate_slippage_stress_bps=slippage,
            candidate_latency_ms=latency,
            candidate_liquidity_score=liquidity,
        ).sealed()


class ExternalMicrostructureAdapterAbstention(CandidateContractModel):
    """A sealed statement that an optional external integration remains unimplemented."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: Literal["abides", "stocksim", "deepmarket"]
    status: Literal["abstained"] = "abstained"
    reason: Literal["integration_not_approved"] = "integration_not_approved"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_content_addressed(self) -> ExternalMicrostructureAdapterAbstention:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("external microstructure abstention content hash mismatch")
        return self

    def sealed(self) -> ExternalMicrostructureAdapterAbstention:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = ExternalMicrostructureAdapterAbstention.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def probe_external_microstructure_adapter(
    adapter: Literal["abides", "stocksim", "deepmarket"],
) -> ExternalMicrostructureAdapterAbstention:
    """Return an explicit abstention without importing or contacting an external adapter."""
    return ExternalMicrostructureAdapterAbstention(adapter=adapter).sealed()
