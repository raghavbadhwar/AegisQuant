"""Bounded, deterministic candidate-only probabilistic scenario contracts."""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from random import Random
from statistics import pvariance
from typing import Literal, cast

from pydantic import ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel


class ScenarioLabel(StrEnum):
    """Explicit scenario labels; none implies an empirical probability claim."""

    BEAR = "bear"
    BASE = "base"
    BULL = "bull"
    MONTE_CARLO = "monte_carlo"


class FrozenParameterArtifact(CandidateContractModel):
    """One finite, bounded candidate parameter or posterior artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1)
    parameter_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    artifact_kind: Literal["parameter", "posterior"] = "posterior"
    distribution: Literal["constant", "normal"]
    lower_bound: float
    upper_bound: float
    mean: float
    standard_deviation: float | None = None
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    calibration_status: Literal["not_calibrated", "release_gated"] = "not_calibrated"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_finite_bounded_distribution(self) -> FrozenParameterArtifact:
        values = (self.lower_bound, self.upper_bound, self.mean)
        if not all(isfinite(value) for value in values) or self.lower_bound >= self.upper_bound:
            raise ValueError("frozen parameter artifact bounds must be finite and ordered")
        if not self.lower_bound <= self.mean <= self.upper_bound:
            raise ValueError("frozen parameter artifact mean must be within its bounds")
        if self.distribution == "normal":
            if self.standard_deviation is None or not isfinite(self.standard_deviation):
                raise ValueError("normal parameter artifact requires a finite standard deviation")
            if self.standard_deviation <= 0.0:
                raise ValueError("normal parameter artifact standard deviation must be positive")
        elif self.standard_deviation is not None:
            raise ValueError("constant parameter artifact cannot declare a standard deviation")
        if any(not evidence_id for evidence_id in self.evidence_ids):
            raise ValueError("frozen parameter artifact evidence IDs must be nonempty")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("frozen parameter artifact evidence IDs must be unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("frozen parameter artifact content hash mismatch")
        return self

    def sealed(self) -> FrozenParameterArtifact:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = FrozenParameterArtifact.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class OutcomeParameterTerm(CandidateContractModel):
    """One bounded linear candidate influence on financial and valuation outputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter_id: str = Field(min_length=1)
    financial_coefficient: float
    valuation_coefficient: float
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_finite_coefficients(self) -> OutcomeParameterTerm:
        if not isfinite(self.financial_coefficient) or not isfinite(self.valuation_coefficient):
            raise ValueError("outcome parameter term coefficients must be finite")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("outcome parameter term content hash mismatch")
        return self

    def sealed(self) -> OutcomeParameterTerm:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = OutcomeParameterTerm.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class BoundedOutcomeModel(CandidateContractModel):
    """Small bounded candidate model, not a market-price or release model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    financial_intercept: float
    valuation_intercept: float
    terms: tuple[OutcomeParameterTerm, ...] = Field(min_length=1)
    financial_bounds: tuple[float, float]
    valuation_bounds: tuple[float, float]
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_finite_bounded_and_sealed(self) -> BoundedOutcomeModel:
        terms = tuple(
            OutcomeParameterTerm.model_validate(term.model_dump(mode="json")) for term in self.terms
        )
        if any(term.content_hash is None for term in terms):
            raise ValueError("bounded outcome model requires sealed terms")
        parameter_ids = [term.parameter_id for term in terms]
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("bounded outcome model parameter IDs must be unique")
        values = (
            self.financial_intercept,
            self.valuation_intercept,
            *self.financial_bounds,
            *self.valuation_bounds,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("bounded outcome model values must be finite")
        if self.financial_bounds[0] >= self.financial_bounds[1]:
            raise ValueError("financial outcome bounds must be ordered")
        if self.valuation_bounds[0] >= self.valuation_bounds[1]:
            raise ValueError("valuation outcome bounds must be ordered")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("bounded outcome model content hash mismatch")
        return self

    def sealed(self) -> BoundedOutcomeModel:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = BoundedOutcomeModel.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class MonteCarloRunManifest(CandidateContractModel):
    """One bounded seed-stable candidate Monte Carlo invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    random_seed: int = Field(ge=0)
    sample_count: int = Field(ge=1, le=10_000)
    parameter_artifacts: tuple[FrozenParameterArtifact, ...] = Field(min_length=1)
    scenario: ScenarioLabel = ScenarioLabel.MONTE_CARLO
    code_revision: str = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_sealed_unique_parameters(self) -> MonteCarloRunManifest:
        parameters = tuple(
            FrozenParameterArtifact.model_validate(parameter.model_dump(mode="json"))
            for parameter in self.parameter_artifacts
        )
        if any(parameter.content_hash is None for parameter in parameters):
            raise ValueError("Monte Carlo manifest requires sealed parameter artifacts")
        parameter_ids = [parameter.parameter_id for parameter in parameters]
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("Monte Carlo manifest parameter IDs must be unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("Monte Carlo manifest content hash mismatch")
        return self

    def sealed(self) -> MonteCarloRunManifest:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = MonteCarloRunManifest.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class ParameterDraw(CandidateContractModel):
    """One exact bounded draw from one frozen artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    draw_index: int = Field(ge=0)
    parameter_id: str = Field(min_length=1)
    parameter_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    value: float
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_finite_and_content_addressed(self) -> ParameterDraw:
        if not isfinite(self.value):
            raise ValueError("parameter draw value must be finite")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("parameter draw content hash mismatch")
        return self

    def sealed(self) -> ParameterDraw:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = ParameterDraw.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class FinancialValuationOutcome(CandidateContractModel):
    """Candidate operating and valuation result; never a price target or authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    draw_index: int = Field(ge=0)
    scenario: ScenarioLabel
    parameter_draws: tuple[ParameterDraw, ...] = Field(min_length=1)
    financial_value: float
    valuation_value: float
    unit: Literal["candidate_value_units"] = "candidate_value_units"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_finite_and_bound_to_sealed_draws(self) -> FinancialValuationOutcome:
        draws = tuple(
            ParameterDraw.model_validate(draw.model_dump(mode="json"))
            for draw in self.parameter_draws
        )
        if any(draw.content_hash is None for draw in draws):
            raise ValueError("financial valuation outcome requires sealed parameter draws")
        parameter_ids = [draw.parameter_id for draw in draws]
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("financial valuation outcome parameter IDs must be unique")
        if not isfinite(self.financial_value) or not isfinite(self.valuation_value):
            raise ValueError("financial valuation outcome values must be finite")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("financial valuation outcome content hash mismatch")
        return self

    def sealed(self) -> FinancialValuationOutcome:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = FinancialValuationOutcome.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class MonteCarloRunResult(CandidateContractModel):
    """Sealed bounded simulation output with all draws retained for replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: MonteCarloRunManifest
    model: BoundedOutcomeModel
    outcomes: tuple[FinancialValuationOutcome, ...] = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def binds_every_outcome_to_one_bounded_run(self) -> MonteCarloRunResult:
        manifest = MonteCarloRunManifest.model_validate(self.manifest.model_dump(mode="json"))
        model = BoundedOutcomeModel.model_validate(self.model.model_dump(mode="json"))
        outcomes = tuple(
            FinancialValuationOutcome.model_validate(outcome.model_dump(mode="json"))
            for outcome in self.outcomes
        )
        if (
            manifest.content_hash is None
            or model.content_hash is None
            or any(outcome.content_hash is None for outcome in outcomes)
        ):
            raise ValueError("Monte Carlo result requires sealed manifest, model, and outcomes")
        if len(outcomes) != manifest.sample_count:
            raise ValueError("Monte Carlo outcome count must match the manifest sample count")
        if [outcome.draw_index for outcome in outcomes] != list(range(manifest.sample_count)):
            raise ValueError("Monte Carlo outcomes must have contiguous deterministic draw indexes")
        if any(outcome.run_id != manifest.run_id for outcome in outcomes):
            raise ValueError("Monte Carlo outcomes must share the manifest run ID")
        parameter_by_id = {
            parameter.parameter_id: parameter for parameter in manifest.parameter_artifacts
        }
        if {term.parameter_id for term in model.terms} != set(parameter_by_id):
            raise ValueError("Monte Carlo model parameters must exactly match the manifest")
        generator = Random(manifest.random_seed)
        ordered_parameters = tuple(
            sorted(manifest.parameter_artifacts, key=lambda item: item.parameter_id)
        )
        for outcome in outcomes:
            if outcome.scenario != manifest.scenario:
                raise ValueError("Monte Carlo outcome scenario does not match the manifest")
            if {draw.parameter_id for draw in outcome.parameter_draws} != set(parameter_by_id):
                raise ValueError(
                    "Monte Carlo outcome draws must exactly match the manifest parameters"
                )
            draws_by_id = {draw.parameter_id: draw for draw in outcome.parameter_draws}
            for parameter in ordered_parameters:
                draw = draws_by_id[parameter.parameter_id]
                if draw.draw_index != outcome.draw_index:
                    raise ValueError("Monte Carlo draw index does not match its outcome")
                if draw.parameter_artifact_hash != parameter.content_hash:
                    raise ValueError(
                        "Monte Carlo draw does not match its frozen parameter artifact"
                    )
                if not parameter.lower_bound <= draw.value <= parameter.upper_bound:
                    raise ValueError("Monte Carlo draw exceeds its frozen parameter bounds")
                expected_draw = _draw_bounded_parameter(parameter, generator)
                if draw.value != expected_draw:
                    raise ValueError(
                        "Monte Carlo draw does not match the manifest seed and artifact"
                    )
            values = {draw.parameter_id: draw.value for draw in outcome.parameter_draws}
            financial_value, valuation_value = _evaluate_bounded_model(model, values)
            if (
                outcome.financial_value != financial_value
                or outcome.valuation_value != valuation_value
            ):
                raise ValueError("Monte Carlo outcome does not reconcile to its retained draws")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("Monte Carlo result content hash mismatch")
        return self

    def sealed(self) -> MonteCarloRunResult:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = MonteCarloRunResult.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def run_bounded_monte_carlo(
    manifest: MonteCarloRunManifest,
    model: BoundedOutcomeModel,
    *,
    scenario: ScenarioLabel | None = None,
) -> MonteCarloRunResult:
    """Run a pure, seed-stable, bounded candidate simulation without I/O."""
    validated_manifest = MonteCarloRunManifest.model_validate(manifest.model_dump(mode="json"))
    validated_model = BoundedOutcomeModel.model_validate(model.model_dump(mode="json"))
    if validated_manifest.content_hash is None or validated_model.content_hash is None:
        raise ValueError("bounded Monte Carlo requires sealed manifest and model")
    if scenario is not None and scenario != validated_manifest.scenario:
        raise ValueError("bounded Monte Carlo scenario must match its manifest")
    parameters = tuple(
        sorted(validated_manifest.parameter_artifacts, key=lambda item: item.parameter_id)
    )
    if {term.parameter_id for term in validated_model.terms} != {
        parameter.parameter_id for parameter in parameters
    }:
        raise ValueError("bounded Monte Carlo model parameters do not match the manifest")
    terms = {term.parameter_id: term for term in validated_model.terms}
    generator = Random(validated_manifest.random_seed)
    outcomes: list[FinancialValuationOutcome] = []
    for draw_index in range(validated_manifest.sample_count):
        draws = tuple(
            ParameterDraw(
                draw_index=draw_index,
                parameter_id=parameter.parameter_id,
                parameter_artifact_hash=cast(str, parameter.content_hash),
                value=_draw_bounded_parameter(parameter, generator),
            ).sealed()
            for parameter in parameters
        )
        values = {draw.parameter_id: draw.value for draw in draws}
        financial_value = validated_model.financial_intercept + sum(
            terms[parameter_id].financial_coefficient * value
            for parameter_id, value in values.items()
        )
        valuation_value = validated_model.valuation_intercept + sum(
            terms[parameter_id].valuation_coefficient * value
            for parameter_id, value in values.items()
        )
        if not _within(financial_value, validated_model.financial_bounds):
            raise ValueError("bounded Monte Carlo financial outcome exceeds declared bounds")
        if not _within(valuation_value, validated_model.valuation_bounds):
            raise ValueError("bounded Monte Carlo valuation outcome exceeds declared bounds")
        outcomes.append(
            FinancialValuationOutcome(
                outcome_id=f"{validated_manifest.run_id}:draw-{draw_index}",
                run_id=validated_manifest.run_id,
                draw_index=draw_index,
                scenario=validated_manifest.scenario,
                parameter_draws=draws,
                financial_value=financial_value,
                valuation_value=valuation_value,
            ).sealed()
        )
    return MonteCarloRunResult(
        manifest=validated_manifest,
        model=validated_model,
        outcomes=tuple(outcomes),
    ).sealed()


def _draw_bounded_parameter(parameter: FrozenParameterArtifact, generator: Random) -> float:
    if parameter.distribution == "constant":
        return parameter.mean
    if parameter.standard_deviation is None:
        raise ValueError("normal parameter artifact requires a standard deviation")
    draw = generator.gauss(parameter.mean, parameter.standard_deviation)
    return min(parameter.upper_bound, max(parameter.lower_bound, draw))


def _within(value: float, bounds: tuple[float, float]) -> bool:
    return isfinite(value) and bounds[0] <= value <= bounds[1]


UncertaintyComponentName = Literal[
    "parameter", "state", "structural", "scenario", "market_response", "residual"
]


class UncertaintyComponentSamples(CandidateContractModel):
    """Sealed engineering samples for one explicitly named uncertainty source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component: UncertaintyComponentName
    samples: tuple[float, ...] = Field(min_length=2)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_finite_content_addressed_samples(self) -> UncertaintyComponentSamples:
        if not all(isfinite(sample) for sample in self.samples):
            raise ValueError("uncertainty component samples must be finite")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("uncertainty component samples content hash mismatch")
        return self

    def sealed(self) -> UncertaintyComponentSamples:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = UncertaintyComponentSamples.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class ComputedUncertaintyDecomposition(CandidateContractModel):
    """Computed candidate variance attribution with no calibration assertion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    components: tuple[UncertaintyComponentSamples, ...] = Field(min_length=1)
    total_variance: float = Field(ge=0.0)
    parameter_share: float = Field(ge=0.0, le=1.0)
    state_share: float = Field(ge=0.0, le=1.0)
    structural_share: float = Field(ge=0.0, le=1.0)
    scenario_share: float = Field(ge=0.0, le=1.0)
    market_response_share: float = Field(ge=0.0, le=1.0)
    residual_share: float = Field(ge=0.0, le=1.0)
    calibration_status: Literal["not_calibrated", "release_gated"] = "not_calibrated"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_bound_to_sealed_components(self) -> ComputedUncertaintyDecomposition:
        components = tuple(
            UncertaintyComponentSamples.model_validate(component.model_dump(mode="json"))
            for component in self.components
        )
        if any(component.content_hash is None for component in components):
            raise ValueError("computed uncertainty decomposition requires sealed components")
        names = [component.component for component in components]
        if len(names) != len(set(names)):
            raise ValueError("computed uncertainty decomposition component names must be unique")
        variances = {component.component: pvariance(component.samples) for component in components}
        total_variance = sum(variances.values())
        component_names: tuple[UncertaintyComponentName, ...] = (
            "parameter",
            "state",
            "structural",
            "scenario",
            "market_response",
            "residual",
        )
        expected_shares = {
            name: (variances.get(name, 0.0) / total_variance if total_variance else 0.0)
            for name in component_names
        }
        actual_shares = {
            "parameter": self.parameter_share,
            "state": self.state_share,
            "structural": self.structural_share,
            "scenario": self.scenario_share,
            "market_response": self.market_response_share,
            "residual": self.residual_share,
        }
        if self.total_variance != total_variance or any(
            actual_shares[name] != expected_shares[name] for name in component_names
        ):
            raise ValueError("computed uncertainty values do not reconcile to sealed components")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("computed uncertainty decomposition content hash mismatch")
        return self

    def sealed(self) -> ComputedUncertaintyDecomposition:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = ComputedUncertaintyDecomposition.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def compute_uncertainty_decomposition(
    components: tuple[UncertaintyComponentSamples, ...],
) -> ComputedUncertaintyDecomposition:
    """Compute population-variance shares from sealed local samples without I/O."""
    validated = tuple(
        UncertaintyComponentSamples.model_validate(component.model_dump(mode="json"))
        for component in components
    )
    if not validated or any(component.content_hash is None for component in validated):
        raise ValueError("uncertainty decomposition requires sealed component samples")
    variances = {component.component: pvariance(component.samples) for component in validated}
    total = sum(variances.values())
    component_names: tuple[UncertaintyComponentName, ...] = (
        "parameter",
        "state",
        "structural",
        "scenario",
        "market_response",
        "residual",
    )
    shares = {
        component: (variances.get(component, 0.0) / total if total else 0.0)
        for component in component_names
    }
    return ComputedUncertaintyDecomposition(
        components=validated,
        total_variance=total,
        parameter_share=shares["parameter"],
        state_share=shares["state"],
        structural_share=shares["structural"],
        scenario_share=shares["scenario"],
        market_response_share=shares["market_response"],
        residual_share=shares["residual"],
    ).sealed()


class OneAtATimeSensitivity(CandidateContractModel):
    """Candidate local sensitivity derived only from one frozen parameter's bounds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: BoundedOutcomeModel
    parameter: FrozenParameterArtifact
    parameter_artifacts: tuple[FrozenParameterArtifact, ...] = Field(min_length=1)
    parameter_id: str = Field(min_length=1)
    low_financial_value: float
    high_financial_value: float
    low_valuation_value: float
    high_valuation_value: float
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_bound_to_sealed_model_and_parameter(self) -> OneAtATimeSensitivity:
        model = BoundedOutcomeModel.model_validate(self.model.model_dump(mode="json"))
        parameter = FrozenParameterArtifact.model_validate(self.parameter.model_dump(mode="json"))
        parameters = tuple(
            FrozenParameterArtifact.model_validate(item.model_dump(mode="json"))
            for item in self.parameter_artifacts
        )
        if (
            model.content_hash is None
            or parameter.content_hash is None
            or any(item.content_hash is None for item in parameters)
        ):
            raise ValueError("one-at-a-time sensitivity requires sealed model and parameters")
        parameters_by_id = {item.parameter_id: item for item in parameters}
        if len(parameters_by_id) != len(parameters) or {
            term.parameter_id for term in model.terms
        } != set(parameters_by_id):
            raise ValueError("one-at-a-time sensitivity parameters do not match its model")
        if self.parameter_id != parameter.parameter_id:
            raise ValueError("one-at-a-time sensitivity parameter ID does not match its artifact")
        if parameters_by_id.get(self.parameter_id) != parameter:
            raise ValueError("one-at-a-time sensitivity parameter is not in its artifacts")
        base_values = {identifier: item.mean for identifier, item in parameters_by_id.items()}
        low_financial, low_valuation = _evaluate_bounded_model(
            model, {**base_values, self.parameter_id: parameter.lower_bound}
        )
        high_financial, high_valuation = _evaluate_bounded_model(
            model, {**base_values, self.parameter_id: parameter.upper_bound}
        )
        if (
            self.low_financial_value != low_financial
            or self.high_financial_value != high_financial
            or self.low_valuation_value != low_valuation
            or self.high_valuation_value != high_valuation
        ):
            raise ValueError("one-at-a-time sensitivity values do not reconcile to sealed inputs")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("one-at-a-time sensitivity content hash mismatch")
        return self

    def sealed(self) -> OneAtATimeSensitivity:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = OneAtATimeSensitivity.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def one_at_a_time_sensitivity(
    model: BoundedOutcomeModel,
    parameters: tuple[FrozenParameterArtifact, ...],
    parameter_id: str,
) -> OneAtATimeSensitivity:
    """Evaluate one frozen parameter at its lower and upper bounds without I/O."""
    validated_model = BoundedOutcomeModel.model_validate(model.model_dump(mode="json"))
    validated_parameters = tuple(
        FrozenParameterArtifact.model_validate(parameter.model_dump(mode="json"))
        for parameter in parameters
    )
    if validated_model.content_hash is None or any(
        parameter.content_hash is None for parameter in validated_parameters
    ):
        raise ValueError("one-at-a-time sensitivity requires sealed inputs")
    parameters_by_id = {parameter.parameter_id: parameter for parameter in validated_parameters}
    if len(parameters_by_id) != len(validated_parameters) or parameter_id not in parameters_by_id:
        raise ValueError("one-at-a-time sensitivity requires one declared frozen parameter")
    if {term.parameter_id for term in validated_model.terms} != set(parameters_by_id):
        raise ValueError("one-at-a-time sensitivity parameters do not match its model")
    base_values = {identifier: parameter.mean for identifier, parameter in parameters_by_id.items()}
    parameter = parameters_by_id[parameter_id]
    low_values = {**base_values, parameter_id: parameter.lower_bound}
    high_values = {**base_values, parameter_id: parameter.upper_bound}
    low_financial, low_valuation = _evaluate_bounded_model(validated_model, low_values)
    high_financial, high_valuation = _evaluate_bounded_model(validated_model, high_values)
    return OneAtATimeSensitivity(
        model=validated_model,
        parameter=parameter,
        parameter_artifacts=validated_parameters,
        parameter_id=parameter_id,
        low_financial_value=low_financial,
        high_financial_value=high_financial,
        low_valuation_value=low_valuation,
        high_valuation_value=high_valuation,
    ).sealed()


def _evaluate_bounded_model(
    model: BoundedOutcomeModel, values: dict[str, float]
) -> tuple[float, float]:
    terms = {term.parameter_id: term for term in model.terms}
    financial_value = model.financial_intercept + sum(
        terms[parameter_id].financial_coefficient * value for parameter_id, value in values.items()
    )
    valuation_value = model.valuation_intercept + sum(
        terms[parameter_id].valuation_coefficient * value for parameter_id, value in values.items()
    )
    if not _within(financial_value, model.financial_bounds):
        raise ValueError("bounded outcome model financial result exceeds declared bounds")
    if not _within(valuation_value, model.valuation_bounds):
        raise ValueError("bounded outcome model valuation result exceeds declared bounds")
    return financial_value, valuation_value


class ScenarioGridPoint(CandidateContractModel):
    """One explicit candidate bear/base/bull coordinate with no probability claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(min_length=1)
    scenario: Literal[ScenarioLabel.BEAR, ScenarioLabel.BASE, ScenarioLabel.BULL]
    parameter_values: tuple[tuple[str, float], ...] = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_unique_finite_values(self) -> ScenarioGridPoint:
        parameter_ids = [parameter_id for parameter_id, _ in self.parameter_values]
        if any(not parameter_id for parameter_id in parameter_ids):
            raise ValueError("scenario grid parameter IDs must be nonempty")
        if len(parameter_ids) != len(set(parameter_ids)):
            raise ValueError("scenario grid parameter IDs must be unique")
        if not all(isfinite(value) for _, value in self.parameter_values):
            raise ValueError("scenario grid parameter values must be finite")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("scenario grid point content hash mismatch")
        return self

    def sealed(self) -> ScenarioGridPoint:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = ScenarioGridPoint.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class ScenarioGridOutcome(CandidateContractModel):
    """One sealed candidate scenario-grid operating and valuation outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    point: ScenarioGridPoint
    scenario_id: str = Field(min_length=1)
    scenario: ScenarioLabel
    financial_value: float
    valuation_value: float
    unit: Literal["candidate_value_units"] = "candidate_value_units"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_bound_to_a_sealed_grid_point(self) -> ScenarioGridOutcome:
        point = ScenarioGridPoint.model_validate(self.point.model_dump(mode="json"))
        if point.content_hash is None:
            raise ValueError("scenario grid outcome requires a sealed grid point")
        if self.scenario_id != point.scenario_id or self.scenario != point.scenario:
            raise ValueError("scenario grid outcome does not match its grid point")
        if not isfinite(self.financial_value) or not isfinite(self.valuation_value):
            raise ValueError("scenario grid outcome values must be finite")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("scenario grid outcome content hash mismatch")
        return self

    def sealed(self) -> ScenarioGridOutcome:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = ScenarioGridOutcome.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class ScenarioGridResult(CandidateContractModel):
    """Sealed candidate grid result, explicitly distinct from a calibrated forecast."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: BoundedOutcomeModel
    parameter_artifacts: tuple[FrozenParameterArtifact, ...] = Field(min_length=1)
    outcomes: tuple[ScenarioGridOutcome, ...] = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_bound_to_sealed_inputs(self) -> ScenarioGridResult:
        model = BoundedOutcomeModel.model_validate(self.model.model_dump(mode="json"))
        parameters = tuple(
            FrozenParameterArtifact.model_validate(parameter.model_dump(mode="json"))
            for parameter in self.parameter_artifacts
        )
        outcomes = tuple(
            ScenarioGridOutcome.model_validate(outcome.model_dump(mode="json"))
            for outcome in self.outcomes
        )
        if model.content_hash is None or any(
            parameter.content_hash is None for parameter in parameters
        ):
            raise ValueError("scenario grid result requires sealed model and parameter artifacts")
        if any(outcome.content_hash is None for outcome in outcomes):
            raise ValueError("scenario grid result requires sealed outcomes")
        parameters_by_id = {parameter.parameter_id: parameter for parameter in parameters}
        if len(parameters_by_id) != len(parameters) or {
            term.parameter_id for term in model.terms
        } != set(parameters_by_id):
            raise ValueError("scenario grid result parameters do not match its model")
        scenario_ids = [outcome.scenario_id for outcome in outcomes]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("scenario grid outcome IDs must be unique")
        for outcome in outcomes:
            values = dict(outcome.point.parameter_values)
            if set(values) != set(parameters_by_id):
                raise ValueError("scenario grid outcome parameters do not match frozen artifacts")
            if any(
                not parameters_by_id[parameter_id].lower_bound
                <= value
                <= parameters_by_id[parameter_id].upper_bound
                for parameter_id, value in values.items()
            ):
                raise ValueError("scenario grid outcome exceeds frozen parameter bounds")
            financial_value, valuation_value = _evaluate_bounded_model(model, values)
            if (
                outcome.financial_value != financial_value
                or outcome.valuation_value != valuation_value
            ):
                raise ValueError("scenario grid outcome does not reconcile to sealed inputs")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("scenario grid result content hash mismatch")
        return self

    def sealed(self) -> ScenarioGridResult:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = ScenarioGridResult.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def evaluate_scenario_grid(
    model: BoundedOutcomeModel,
    parameters: tuple[FrozenParameterArtifact, ...],
    points: tuple[ScenarioGridPoint, ...],
) -> ScenarioGridResult:
    """Evaluate declared bear/base/bull grid points through the bounded candidate model."""
    validated_model = BoundedOutcomeModel.model_validate(model.model_dump(mode="json"))
    validated_parameters = tuple(
        FrozenParameterArtifact.model_validate(parameter.model_dump(mode="json"))
        for parameter in parameters
    )
    validated_points = tuple(
        ScenarioGridPoint.model_validate(point.model_dump(mode="json")) for point in points
    )
    if (
        validated_model.content_hash is None
        or any(parameter.content_hash is None for parameter in validated_parameters)
        or any(point.content_hash is None for point in validated_points)
    ):
        raise ValueError("scenario grid requires sealed inputs")
    parameters_by_id = {parameter.parameter_id: parameter for parameter in validated_parameters}
    if len(parameters_by_id) != len(validated_parameters) or {
        term.parameter_id for term in validated_model.terms
    } != set(parameters_by_id):
        raise ValueError("scenario grid parameters do not match its model")
    outcomes: list[ScenarioGridOutcome] = []
    for point in validated_points:
        values = dict(point.parameter_values)
        if set(values) != set(parameters_by_id):
            raise ValueError("scenario grid point parameters do not match the frozen artifacts")
        if any(
            not parameters_by_id[parameter_id].lower_bound
            <= value
            <= parameters_by_id[parameter_id].upper_bound
            for parameter_id, value in values.items()
        ):
            raise ValueError("scenario grid point exceeds frozen parameter bounds")
        financial_value, valuation_value = _evaluate_bounded_model(validated_model, values)
        outcomes.append(
            ScenarioGridOutcome(
                point=point,
                scenario_id=point.scenario_id,
                scenario=point.scenario,
                financial_value=financial_value,
                valuation_value=valuation_value,
            ).sealed()
        )
    return ScenarioGridResult(
        model=validated_model,
        parameter_artifacts=validated_parameters,
        outcomes=tuple(outcomes),
    ).sealed()
