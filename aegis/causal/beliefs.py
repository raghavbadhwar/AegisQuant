"""Candidate-only Bayesian belief records; never factual or execution authority."""

from __future__ import annotations

from pydantic import ConfigDict, Field, model_validator

from aegis.contracts._base import CandidateContractModel


class BeliefState(CandidateContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    belief_id: str = Field(min_length=1)
    proposition: str = Field(min_length=1)
    prior_probability: float = Field(ge=0, le=1)
    posterior_probability: float = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    calibration_status: str = Field(min_length=1)
    factuality: str = "candidate_belief"

    @model_validator(mode="after")
    def belief_is_not_fact_and_updates_need_evidence(self) -> BeliefState:
        if self.factuality != "candidate_belief":
            raise ValueError("belief state cannot claim factual authority")
        if self.posterior_probability != self.prior_probability and not self.evidence_ids:
            raise ValueError("belief update requires evidence")
        return self
