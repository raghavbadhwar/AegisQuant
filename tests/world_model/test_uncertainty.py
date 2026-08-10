from __future__ import annotations

import pytest

from aegis.world_model.uncertainty import (
    DistributionKind,
    DistributionSpec,
    ProbabilityCalibrationStatus,
    ProbabilityProvenance,
    UncertaintyDecomposition,
)


def test_stress_only_distribution_cannot_claim_a_probability() -> None:
    with pytest.raises(ValueError, match="stress-only distribution cannot declare a probability"):
        DistributionSpec(
            distribution_id="stress-capex-drop",
            kind=DistributionKind.CONSTANT,
            parameters=(("value", -0.2),),
            probability_provenance=ProbabilityProvenance.STRESS_ONLY_NOT_PROBABILISTIC,
            calibration_status=ProbabilityCalibrationStatus.NOT_CALIBRATED,
            probability=0.5,
        )


def test_model_posterior_distribution_requires_a_frozen_artifact_reference() -> None:
    with pytest.raises(
        ValueError, match="model posterior distribution requires a posterior artifact"
    ):
        DistributionSpec(
            distribution_id="capex-elasticity-posterior",
            kind=DistributionKind.NORMAL,
            parameters=(("mean", 0.4), ("stddev", 0.1)),
            probability_provenance=ProbabilityProvenance.MODEL_POSTERIOR,
            calibration_status=ProbabilityCalibrationStatus.NOT_CALIBRATED,
        )


def test_normal_distribution_requires_a_positive_standard_deviation() -> None:
    with pytest.raises(ValueError, match="normal distribution requires a positive stddev"):
        DistributionSpec(
            distribution_id="invalid-normal",
            kind=DistributionKind.NORMAL,
            parameters=(("mean", 0.0), ("stddev", 0.0)),
            probability_provenance=ProbabilityProvenance.MODEL_POSTERIOR,
            calibration_status=ProbabilityCalibrationStatus.NOT_CALIBRATED,
            posterior_artifact_id="posterior-v1",
        )


def test_calibrated_distribution_requires_a_calibration_reference() -> None:
    with pytest.raises(
        ValueError, match="calibrated distribution requires a calibration reference"
    ):
        DistributionSpec(
            distribution_id="calibrated-posterior",
            kind=DistributionKind.NORMAL,
            parameters=(("mean", 0.0), ("stddev", 0.1)),
            probability_provenance=ProbabilityProvenance.MODEL_POSTERIOR,
            calibration_status=ProbabilityCalibrationStatus.CALIBRATED,
            posterior_artifact_id="posterior-v1",
        )


def test_scenario_weight_requires_an_explicit_probability() -> None:
    with pytest.raises(ValueError, match="scenario weight requires a probability"):
        DistributionSpec(
            distribution_id="weighted-slowdown",
            kind=DistributionKind.CONSTANT,
            parameters=(("value", -0.2),),
            probability_provenance=ProbabilityProvenance.SCENARIO_WEIGHT,
            calibration_status=ProbabilityCalibrationStatus.NOT_CALIBRATED,
        )


def test_uncertainty_decomposition_rejects_negative_components() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        UncertaintyDecomposition(
            total_variance=1.0,
            parameter_share=-0.1,
            state_share=0.1,
            structural_share=0.1,
            scenario_share=0.1,
            market_response_share=0.1,
            residual_share=0.5,
            probability_calibration_status=ProbabilityCalibrationStatus.NOT_CALIBRATED,
        )


def test_calibrated_uncertainty_decomposition_requires_calibration_reference() -> None:
    with pytest.raises(
        ValueError, match="calibrated uncertainty decomposition requires a calibration reference"
    ):
        UncertaintyDecomposition(
            total_variance=1.0,
            parameter_share=0.2,
            state_share=0.2,
            structural_share=0.1,
            scenario_share=0.2,
            market_response_share=0.2,
            residual_share=0.1,
            probability_calibration_status=ProbabilityCalibrationStatus.CALIBRATED,
        )


def test_uncertainty_shares_must_sum_to_one_when_variance_is_positive() -> None:
    with pytest.raises(ValueError, match="uncertainty shares must sum to one"):
        UncertaintyDecomposition(
            total_variance=1.0,
            parameter_share=0.2,
            state_share=0.2,
            structural_share=0.2,
            scenario_share=0.2,
            market_response_share=0.2,
            residual_share=0.2,
            probability_calibration_status=ProbabilityCalibrationStatus.NOT_CALIBRATED,
        )
