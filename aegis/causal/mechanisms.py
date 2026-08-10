"""Candidate-only structural mechanism definitions for v4 causal theses."""

from __future__ import annotations

from pydantic import ConfigDict, Field, model_validator

from aegis.contracts._base import CandidateContractModel


class MechanismDefinition(CandidateContractModel):
    """A testable mechanism, not a factual, pricing, or execution authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mechanism_id: str = Field(min_length=1)
    causal_edge_id: str = Field(min_length=1)
    domain_pack: str = Field(min_length=1)
    input_variable_ids: tuple[str, ...] = Field(min_length=1)
    output_variable_ids: tuple[str, ...] = Field(min_length=1)
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    validation_case_ids: tuple[str, ...] = ()
    status: str = "candidate"
    authority: str = "candidate_only"

    @model_validator(mode="after")
    def mechanism_is_testable_and_non_authoritative(self) -> MechanismDefinition:
        if self.authority != "candidate_only":
            raise ValueError("mechanism cannot receive execution or factual authority")
        if set(self.input_variable_ids).intersection(self.output_variable_ids):
            raise ValueError("mechanism input and output variables must be distinct")
        if self.status == "validated" and (not self.evidence_ids or not self.validation_case_ids):
            raise ValueError("validated mechanism requires evidence and validation cases")
        return self
