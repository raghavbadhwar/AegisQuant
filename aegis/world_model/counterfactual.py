"""Fail-closed, candidate-only counterfactual contracts with no simulation path."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.causal.contracts import CausalEdgeKind, CausalGraphSnapshot, CausalSupportLevel
from aegis.causal.mechanisms import MechanismDefinition
from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel

from .contracts import ScenarioIntervention, WorldSnapshot


class CounterfactualStatus(StrEnum):
    COUNTERFACTUAL_NOT_IDENTIFIED = "COUNTERFACTUAL_NOT_IDENTIFIED"
    COUNTERFACTUAL_NOT_SIMULATED = "COUNTERFACTUAL_NOT_SIMULATED"


class CounterfactualPostMortemStatus(StrEnum):
    """A post-mortem preserves abstention; it never infers a causal result."""

    ABSTAINED_INSUFFICIENT_SUPPORT = "abstained_insufficient_support"
    ABSTAINED_NOT_SIMULATED = "abstained_not_simulated"


class CausalMechanismApproval(CandidateContractModel):
    """Content-addressed candidate attestation; it is not authenticated human approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1)
    mechanism_id: str = Field(min_length=1)
    mechanism_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    causal_graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    domain_pack: str = Field(min_length=1)
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    human_approver_id: str = Field(min_length=1)
    approved_at: AwareDatetime
    expires_at: AwareDatetime
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def binds_a_nonexpired_approval(self) -> CausalMechanismApproval:
        if self.expires_at <= self.approved_at:
            raise ValueError("mechanism approval must expire after approval time")
        if any(not assumption_id for assumption_id in self.assumption_ids) or len(
            self.assumption_ids
        ) != len(set(self.assumption_ids)):
            raise ValueError("mechanism approval assumption IDs must be unique and nonempty")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("mechanism approval content hash mismatch")
        return self

    def sealed(self) -> CausalMechanismApproval:
        return self.model_copy(
            update={
                "content_hash": canonical_sha256(
                    self.model_dump(mode="json", exclude={"content_hash"})
                )
            }
        )


class CounterfactualRequest(CandidateContractModel):
    """A counterfactual research request, not an instruction to simulate or act."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    world_snapshot: WorldSnapshot
    intervention: ScenarioIntervention
    causal_graph: CausalGraphSnapshot | None = None
    mechanisms: tuple[MechanismDefinition, ...] = ()
    mechanism_approvals: tuple[CausalMechanismApproval, ...] = ()
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def requires_nonempty_unique_assumptions(self) -> CounterfactualRequest:
        if any(not assumption_id for assumption_id in self.assumption_ids):
            raise ValueError("counterfactual assumption IDs must be nonempty")
        if len(self.assumption_ids) != len(set(self.assumption_ids)):
            raise ValueError("counterfactual assumption IDs must be unique")
        return self


class CounterfactualOutcome(CandidateContractModel):
    """Typed abstention only; it deliberately contains no simulated values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    status: CounterfactualStatus
    reason: str = Field(min_length=1)
    world_snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    intervention_id: str = Field(min_length=1)
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    outcome_variables: tuple[str, ...] = ()
    simulated: Literal[False] = False
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def is_a_bound_abstention_without_conclusions(self) -> CounterfactualOutcome:
        if self.world_snapshot_hash is None:
            raise ValueError("counterfactual abstention requires a bound world snapshot hash")
        if self.outcome_variables:
            raise ValueError("counterfactual abstention cannot include outcome variables")
        if any(not assumption_id for assumption_id in self.assumption_ids) or len(
            self.assumption_ids
        ) != len(set(self.assumption_ids)):
            raise ValueError("counterfactual abstention assumptions must be nonempty and unique")
        return self


class CounterfactualPostMortem(CandidateContractModel):
    """A sealed record of an abstention, never a counterfactual conclusion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    post_mortem_id: str = Field(min_length=1)
    counterfactual_outcome: CounterfactualOutcome
    counterfactual_outcome_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CounterfactualPostMortemStatus
    reason: str = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def preserves_the_bound_abstention(self) -> CounterfactualPostMortem:
        outcome = CounterfactualOutcome.model_validate(
            self.counterfactual_outcome.model_dump(mode="json")
        )
        outcome_hash = canonical_sha256(outcome.model_dump(mode="json"))
        expected_status = (
            CounterfactualPostMortemStatus.ABSTAINED_INSUFFICIENT_SUPPORT
            if outcome.status == CounterfactualStatus.COUNTERFACTUAL_NOT_IDENTIFIED
            else CounterfactualPostMortemStatus.ABSTAINED_NOT_SIMULATED
        )
        if (
            self.counterfactual_outcome_hash != outcome_hash
            or self.status != expected_status
            or self.reason != outcome.reason
        ):
            raise ValueError("counterfactual post-mortem must preserve its source abstention")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("counterfactual post-mortem content hash mismatch")
        return self

    def sealed(self) -> CounterfactualPostMortem:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = CounterfactualPostMortem.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def _has_identified_approved_inputs(request: CounterfactualRequest) -> bool:
    """Validate only structural eligibility; it deliberately performs no propagation."""
    if request.causal_graph is None or not request.mechanism_approvals:
        return False

    try:
        graph = CausalGraphSnapshot.model_validate(request.causal_graph.model_dump(mode="json"))
        snapshot = WorldSnapshot.model_validate(request.world_snapshot.model_dump(mode="json"))
        intervention = ScenarioIntervention.model_validate(
            request.intervention.model_dump(mode="json")
        )
        mechanisms = tuple(
            MechanismDefinition.model_validate(mechanism.model_dump(mode="json"))
            for mechanism in request.mechanisms
        )
        approvals = tuple(
            CausalMechanismApproval.model_validate(approval.model_dump(mode="json"))
            for approval in request.mechanism_approvals
        )
    except ValueError:
        return False

    if (
        graph.content_hash is None
        or snapshot.content_hash is None
        or graph.content_hash != snapshot.causal_graph_hash
        or graph.as_of > snapshot.as_of
        or intervention.starts_at < snapshot.as_of
        or intervention.target_variable_id
        not in {variable.variable_id for variable in snapshot.variables}
    ):
        return False

    identified_edge_ids = {
        edge.edge_id
        for edge in graph.eligible_edges()
        if edge.kind in {CausalEdgeKind.IDENTIFIED_CAUSE, CausalEdgeKind.STRUCTURAL_MECHANISM}
        and edge.support_level
        in {CausalSupportLevel.C2_IDENTIFIED, CausalSupportLevel.C3_STRUCTURAL}
    }
    applicable_mechanisms = tuple(
        mechanism
        for mechanism in mechanisms
        if mechanism.status == "validated"
        and mechanism.domain_pack == graph.domain_pack
        and mechanism.causal_edge_id in identified_edge_ids
        and intervention.target_variable_id in mechanism.input_variable_ids
    )
    mechanism_ids = [mechanism.mechanism_id for mechanism in applicable_mechanisms]
    if (
        not identified_edge_ids
        or not mechanism_ids
        or len(mechanism_ids) != len(set(mechanism_ids))
    ):
        return False

    approval_ids = [approval.approval_id for approval in approvals]
    approval_by_mechanism = {approval.mechanism_id: approval for approval in approvals}
    if (
        len(approval_ids) != len(set(approval_ids))
        or len(approval_by_mechanism) != len(approvals)
        or set(approval_by_mechanism) != set(mechanism_ids)
    ):
        return False

    return all(
        approval.content_hash is not None
        and approval.mechanism_content_hash == canonical_sha256(mechanism.model_dump(mode="json"))
        and approval.causal_graph_hash == graph.content_hash
        and approval.domain_pack == graph.domain_pack
        and approval.assumption_ids == mechanism.assumption_ids == request.assumption_ids
        and approval.approved_at <= snapshot.as_of < approval.expires_at
        for mechanism in applicable_mechanisms
        for approval in (approval_by_mechanism[mechanism.mechanism_id],)
    )


def resolve_counterfactual(request: CounterfactualRequest) -> CounterfactualOutcome:
    """Fail closed and never simulate, even when structural inputs are supplied."""
    identified_and_approved = _has_identified_approved_inputs(request)
    return CounterfactualOutcome(
        request_id=request.request_id,
        status=(
            CounterfactualStatus.COUNTERFACTUAL_NOT_SIMULATED
            if identified_and_approved
            else CounterfactualStatus.COUNTERFACTUAL_NOT_IDENTIFIED
        ),
        reason=(
            "The request contains candidate graph and mechanism-approval bindings, but this "
            "candidate-only contract slice does not simulate outcomes."
            if identified_and_approved
            else "Counterfactual is not identified: an identified causal graph and approved "
            "mechanisms are required."
        ),
        world_snapshot_hash=request.world_snapshot.content_hash,
        intervention_id=request.intervention.intervention_id,
        assumption_ids=request.assumption_ids,
    )


def create_counterfactual_post_mortem(
    post_mortem_id: str, outcome: CounterfactualOutcome
) -> CounterfactualPostMortem:
    """Bind one candidate post-mortem to the original no-conclusion outcome."""
    validated = CounterfactualOutcome.model_validate(outcome.model_dump(mode="json"))
    status = (
        CounterfactualPostMortemStatus.ABSTAINED_INSUFFICIENT_SUPPORT
        if validated.status == CounterfactualStatus.COUNTERFACTUAL_NOT_IDENTIFIED
        else CounterfactualPostMortemStatus.ABSTAINED_NOT_SIMULATED
    )
    return CounterfactualPostMortem(
        post_mortem_id=post_mortem_id,
        counterfactual_outcome=validated,
        counterfactual_outcome_hash=canonical_sha256(validated.model_dump(mode="json")),
        status=status,
        reason=validated.reason,
    ).sealed()
