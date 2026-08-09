import pytest

from aegis.causal import BeliefState


def test_changed_belief_requires_evidence() -> None:
    with pytest.raises(ValueError, match="evidence"):
        BeliefState(
            belief_id="b",
            proposition="x",
            prior_probability=0.2,
            posterior_probability=0.4,
            calibration_status="uncalibrated",
        )


def test_belief_cannot_claim_factual_authority() -> None:
    with pytest.raises(ValueError, match="factual"):
        BeliefState(
            belief_id="b",
            proposition="x",
            prior_probability=0.2,
            posterior_probability=0.2,
            calibration_status="uncalibrated",
            factuality="fact",
        )
