"""Strict, candidate-only contracts for planning research value of information."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from aegis.contracts._base import CandidateContractModel


class ResearchAction(CandidateContractModel):
    """A proposed research activity descriptor; it cannot perform the activity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    expected_information_value: float = Field(ge=0.0)
    research_cost: float = Field(ge=0.0)
    latency_cost: float = Field(ge=0.0)
    model_cost: float = Field(ge=0.0)
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def requires_distinct_nonempty_assumptions(self) -> ResearchAction:
        if any(not assumption_id for assumption_id in self.assumption_ids):
            raise ValueError("research action assumption IDs must be nonempty")
        if len(self.assumption_ids) != len(set(self.assumption_ids)):
            raise ValueError("research action assumption IDs must be unique")
        return self


class ValueOfInformationResult(CandidateContractModel):
    """Auditable heuristic score, never an authorization to perform research."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1)
    expected_information_value: float = Field(ge=0.0)
    research_cost: float = Field(ge=0.0)
    latency_cost: float = Field(ge=0.0)
    model_cost: float = Field(ge=0.0)
    total_cost: float = Field(ge=0.0)
    net_voi: float
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    rank: int = Field(ge=1)
    stop_research: bool
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def total_and_net_voi_are_bound_to_inputs(self) -> ValueOfInformationResult:
        expected_total_cost = self.research_cost + self.latency_cost + self.model_cost
        expected_net_voi = self.expected_information_value - expected_total_cost
        if not math.isclose(self.total_cost, expected_total_cost, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("total cost must include research, latency, and model costs")
        if not math.isclose(self.net_voi, expected_net_voi, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("net VOI must equal expected information value minus total cost")
        return self
