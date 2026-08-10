"""Candidate-only uncertainty contracts for the v4 world model."""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import ConfigDict, Field, model_validator

from aegis.contracts._base import CandidateContractModel


class DistributionKind(StrEnum):
    CONSTANT = "constant"
    NORMAL = "normal"


class ProbabilityProvenance(StrEnum):
    MODEL_POSTERIOR = "model_posterior"
    SCENARIO_WEIGHT = "scenario_weight"
    STRESS_ONLY_NOT_PROBABILISTIC = "stress_only_not_probabilistic"


class ProbabilityCalibrationStatus(StrEnum):
    NOT_CALIBRATED = "not_calibrated"
    CALIBRATED = "calibrated"


class DistributionSpec(CandidateContractModel):
    """One explicitly labelled candidate distribution or non-probabilistic stress."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    distribution_id: str = Field(min_length=1)
    kind: DistributionKind
    parameters: tuple[tuple[str, float], ...]
    probability_provenance: ProbabilityProvenance
    calibration_status: ProbabilityCalibrationStatus
    probability: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    posterior_artifact_id: str | None = Field(default=None, min_length=1)
    calibration_reference_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def probability_semantics_are_explicit(self) -> DistributionSpec:
        parameters = dict(self.parameters)
        if self.kind == DistributionKind.NORMAL:
            stddev = parameters.get("stddev")
            if stddev is None or not math.isfinite(stddev) or stddev <= 0.0:
                raise ValueError("normal distribution requires a positive stddev")
        if (
            self.probability_provenance == ProbabilityProvenance.SCENARIO_WEIGHT
            and self.probability is None
        ):
            raise ValueError("scenario weight requires a probability")
        if (
            self.probability_provenance == ProbabilityProvenance.STRESS_ONLY_NOT_PROBABILISTIC
            and self.probability is not None
        ):
            raise ValueError("stress-only distribution cannot declare a probability")
        if (
            self.probability_provenance == ProbabilityProvenance.MODEL_POSTERIOR
            and self.posterior_artifact_id is None
        ):
            raise ValueError("model posterior distribution requires a posterior artifact")
        if (
            self.calibration_status == ProbabilityCalibrationStatus.CALIBRATED
            and self.calibration_reference_id is None
        ):
            raise ValueError("calibrated distribution requires a calibration reference")
        return self


class UncertaintyDecomposition(CandidateContractModel):
    """Variance attribution with explicit, non-authoritative calibration status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_variance: float = Field(ge=0.0, allow_inf_nan=False)
    parameter_share: float = Field(ge=0.0, allow_inf_nan=False)
    state_share: float = Field(ge=0.0, allow_inf_nan=False)
    structural_share: float = Field(ge=0.0, allow_inf_nan=False)
    scenario_share: float = Field(ge=0.0, allow_inf_nan=False)
    market_response_share: float = Field(ge=0.0, allow_inf_nan=False)
    residual_share: float = Field(ge=0.0, allow_inf_nan=False)
    probability_calibration_status: ProbabilityCalibrationStatus
    calibration_reference_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def calibration_claim_is_evidenced(self) -> UncertaintyDecomposition:
        if (
            self.probability_calibration_status == ProbabilityCalibrationStatus.CALIBRATED
            and self.calibration_reference_id is None
        ):
            raise ValueError(
                "calibrated uncertainty decomposition requires a calibration reference"
            )
        if self.total_variance > 0.0 and not math.isclose(
            self.parameter_share
            + self.state_share
            + self.structural_share
            + self.scenario_share
            + self.market_response_share
            + self.residual_share,
            1.0,
            abs_tol=1e-9,
        ):
            raise ValueError("uncertainty shares must sum to one")
        return self
