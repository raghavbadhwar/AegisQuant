"""Candidate-only Bayesian belief records; never factual or execution authority."""

from __future__ import annotations

from itertools import pairwise

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
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


class BeliefRevision(CandidateContractModel):
    """One immutable candidate-belief update, never factual or decision authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_id: str = Field(min_length=1)
    belief_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    as_of: AwareDatetime
    prior_probability: float = Field(ge=0.0, le=1.0)
    posterior_probability: float = Field(ge=0.0, le=1.0)
    evidence_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    parent_revision_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    authority: str = "candidate_only"
    factuality: str = "candidate_belief"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_candidate_only_and_content_addressed(self) -> BeliefRevision:
        if self.authority != "candidate_only" or self.factuality != "candidate_belief":
            raise ValueError("belief revision cannot claim factual or decision authority")
        if (self.sequence == 1) != (self.parent_revision_hash is None):
            raise ValueError("belief revision parent hash must match its sequence")
        if self.posterior_probability != self.prior_probability and not self.evidence_ids:
            raise ValueError("changed belief revision requires evidence")
        for identifiers, name in (
            (self.evidence_ids, "evidence"),
            (self.assumption_ids, "assumption"),
        ):
            if any(not identifier for identifier in identifiers) or len(identifiers) != len(
                set(identifiers)
            ):
                raise ValueError(f"belief revision {name} IDs must be nonempty and unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("belief revision content hash mismatch")
        return self

    def sealed(self) -> BeliefRevision:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = BeliefRevision.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class BeliefRevisionLedger(CandidateContractModel):
    """One immutable append-only candidate-belief lineage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revisions: tuple[BeliefRevision, ...] = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_a_single_verified_lineage(self) -> BeliefRevisionLedger:
        revisions = tuple(
            BeliefRevision.model_validate(revision.model_dump(mode="json"))
            for revision in self.revisions
        )
        if any(revision.content_hash is None for revision in revisions):
            raise ValueError("belief revision ledger requires sealed revisions")
        if revisions[0].sequence != 1 or revisions[0].parent_revision_hash is not None:
            raise ValueError("belief revision ledger must begin with a root revision")
        if len({revision.revision_id for revision in revisions}) != len(revisions):
            raise ValueError("belief revision ledger revision IDs must be unique")
        if len({revision.belief_id for revision in revisions}) != 1:
            raise ValueError("belief revision ledger must contain one belief lineage")
        for predecessor, revision in pairwise(revisions):
            if revision.sequence != predecessor.sequence + 1:
                raise ValueError("belief revision ledger sequence must be append-only")
            if revision.parent_revision_hash != predecessor.content_hash:
                raise ValueError("belief revision ledger parent revision hash is inconsistent")
            if revision.as_of < predecessor.as_of:
                raise ValueError("belief revision ledger timestamps must be chronological")
            if revision.prior_probability != predecessor.posterior_probability:
                raise ValueError("belief revision prior probability must match its predecessor")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("belief revision ledger content hash mismatch")
        return self

    def sealed(self) -> BeliefRevisionLedger:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = BeliefRevisionLedger.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})

    def append(self, revision: BeliefRevision) -> BeliefRevisionLedger:
        """Append one exact successor without mutating or replacing prior revisions."""
        validated = BeliefRevisionLedger.model_validate(self.model_dump(mode="json"))
        if validated.content_hash is None:
            raise ValueError("belief revision ledger must be sealed before appending")
        return BeliefRevisionLedger(revisions=(*validated.revisions, revision)).sealed()
