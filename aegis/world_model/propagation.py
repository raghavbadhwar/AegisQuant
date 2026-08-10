"""Pure, candidate-only lagged economic-network propagation."""

from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel

from .ai_infrastructure import MechanismRegistry
from .contracts import WorldSnapshot
from .contributions import EffectContribution, EffectContributionLedger, TargetEffectReconciliation


class NetworkPropagationEdge(CandidateContractModel):
    """One bounded candidate transmission path with an explicit business-step lag."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: str = Field(min_length=1)
    source_variable_id: str = Field(min_length=1)
    source_unit: str = Field(min_length=1)
    target_variable_id: str = Field(min_length=1)
    target_unit: str = Field(min_length=1)
    multiplier: float
    lag_steps: int = Field(ge=0)
    mechanism_model_id: str = Field(min_length=1)
    path_id: str = Field(min_length=1)
    overlap_adjustment: float = 0.0
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_bounded_and_content_addressed(self) -> NetworkPropagationEdge:
        if not isfinite(self.multiplier) or not isfinite(self.overlap_adjustment):
            raise ValueError("network propagation edge values must be finite")
        if any(not assumption_id for assumption_id in self.assumption_ids):
            raise ValueError("network propagation edge assumption IDs must be nonempty")
        if len(self.assumption_ids) != len(set(self.assumption_ids)):
            raise ValueError("network propagation edge assumption IDs must be unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("network propagation edge content hash mismatch")
        return self

    def sealed(self) -> NetworkPropagationEdge:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = NetworkPropagationEdge.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class NetworkPropagationPlan(CandidateContractModel):
    """Sealed acyclic propagation plan; feedback requires the separate explicit solver."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(min_length=1)
    domain_pack_id: str = Field(min_length=1)
    domain_pack_version: str = Field(min_length=1)
    world_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    world_snapshot: WorldSnapshot
    mechanism_registry: MechanismRegistry
    edges: tuple[NetworkPropagationEdge, ...] = Field(min_length=1)
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_unique_acyclic_edges(self) -> NetworkPropagationPlan:
        edges = tuple(
            NetworkPropagationEdge.model_validate(edge.model_dump(mode="json"))
            for edge in self.edges
        )
        registry = MechanismRegistry.model_validate(self.mechanism_registry.model_dump(mode="json"))
        snapshot = WorldSnapshot.model_validate(self.world_snapshot.model_dump(mode="json"))
        if any(edge.content_hash is None for edge in edges):
            raise ValueError("network propagation plan requires sealed edges")
        if snapshot.content_hash is None:
            raise ValueError("network propagation plan requires a sealed world snapshot")
        if self.world_snapshot_hash != snapshot.content_hash:
            raise ValueError("network propagation plan world snapshot hash does not match")
        if registry.content_hash is None:
            raise ValueError("network propagation plan requires a sealed mechanism registry")
        if (
            registry.domain_pack_id != self.domain_pack_id
            or registry.domain_pack_version != self.domain_pack_version
        ):
            raise ValueError("network propagation plan mechanism registry domain does not match")
        mechanisms_by_id = {
            mechanism.mechanism.mechanism_id: mechanism for mechanism in registry.mechanisms
        }
        if len(mechanisms_by_id) != len(registry.mechanisms):
            raise ValueError(
                "network propagation plan requires one registered mechanism version per ID"
            )
        for edge in edges:
            mechanism = mechanisms_by_id.get(edge.mechanism_model_id)
            if mechanism is None:
                raise ValueError("network propagation edge mechanism is not registered")
            if (
                edge.source_variable_id not in mechanism.mechanism.input_variable_ids
                or edge.target_variable_id not in mechanism.mechanism.output_variable_ids
            ):
                raise ValueError(
                    "network propagation edge variables do not match its registered mechanism"
                )
            if mechanism.causal_graph_hash != snapshot.causal_graph_hash:
                raise ValueError(
                    "network propagation edge mechanism causal graph does not match its snapshot"
                )
        edge_ids = [edge.edge_id for edge in edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("network propagation edge IDs must be unique")
        paths = [
            (
                edge.source_variable_id,
                edge.target_variable_id,
                edge.mechanism_model_id,
                edge.lag_steps,
            )
            for edge in edges
        ]
        if len(paths) != len(set(paths)):
            raise ValueError("network propagation economic paths must be unique")
        if _has_cycle(edges):
            raise ValueError("network propagation feedback requires an explicit feedback solver")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("network propagation plan content hash mismatch")
        return self

    def sealed(self) -> NetworkPropagationPlan:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = NetworkPropagationPlan.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class FeedbackVariable(CandidateContractModel):
    """One finite, unit-bearing feedback-state value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variable_id: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_finite_and_content_addressed(self) -> FeedbackVariable:
        if not isfinite(self.value):
            raise ValueError("feedback variable value must be finite")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("feedback variable content hash mismatch")
        return self

    def sealed(self) -> FeedbackVariable:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = FeedbackVariable.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class FeedbackRule(CandidateContractModel):
    """One unit-preserving feedback equation term."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1)
    source_variable_id: str = Field(min_length=1)
    target_variable_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    multiplier: float
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_finite_and_content_addressed(self) -> FeedbackRule:
        if not isfinite(self.multiplier):
            raise ValueError("feedback rule multiplier must be finite")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("feedback rule content hash mismatch")
        return self

    def sealed(self) -> FeedbackRule:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = FeedbackRule.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class FeedbackConvergencePolicy(CandidateContractModel):
    """Explicit fixed-point convergence budget for a candidate feedback loop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str = Field(min_length=1)
    tolerance: float = Field(gt=0.0)
    max_iterations: int = Field(ge=1, le=10_000)
    damping: float = Field(gt=0.0, le=1.0)
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_finite_and_content_addressed(self) -> FeedbackConvergencePolicy:
        if not isfinite(self.tolerance) or not isfinite(self.damping):
            raise ValueError("feedback convergence policy values must be finite")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("feedback convergence policy content hash mismatch")
        return self

    def sealed(self) -> FeedbackConvergencePolicy:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = FeedbackConvergencePolicy.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class FeedbackSolveResult(CandidateContractModel):
    """Sealed converged result; non-convergence is an explicit function failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy: FeedbackConvergencePolicy
    values: tuple[FeedbackVariable, ...] = Field(min_length=1)
    iterations: int = Field(ge=1)
    converged: Literal[True] = True
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_bound_to_a_sealed_policy(self) -> FeedbackSolveResult:
        policy = FeedbackConvergencePolicy.model_validate(self.policy.model_dump(mode="json"))
        values = tuple(
            FeedbackVariable.model_validate(value.model_dump(mode="json")) for value in self.values
        )
        if policy.content_hash is None:
            raise ValueError("feedback result requires a sealed policy")
        if self.policy_hash != policy.content_hash:
            raise ValueError("feedback result policy hash does not match its policy")
        if any(value.content_hash is None for value in values):
            raise ValueError("feedback result requires sealed values")
        variable_ids = [value.variable_id for value in values]
        if len(variable_ids) != len(set(variable_ids)):
            raise ValueError("feedback result variable IDs must be unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("feedback result content hash mismatch")
        return self

    def sealed(self) -> FeedbackSolveResult:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = FeedbackSolveResult.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def propagate_effect(
    root_effect: EffectContribution, plan: NetworkPropagationPlan
) -> EffectContributionLedger:
    """Propagate one effect deterministically, preserving parentage and exact reconciliation."""
    root = EffectContribution.model_validate(root_effect.model_dump(mode="json"))
    validated_plan = NetworkPropagationPlan.model_validate(plan.model_dump(mode="json"))
    if validated_plan.content_hash is None:
        raise ValueError("network propagation requires a sealed plan")
    outgoing: dict[str, list[NetworkPropagationEdge]] = defaultdict(list)
    for edge in validated_plan.edges:
        outgoing[edge.source_variable_id].append(edge)
    contributions = [root]
    pending = [root]
    target_steps = {(root.target_variable_id, root.units, root.time_step)}
    while pending:
        parent = pending.pop(0)
        for edge in sorted(outgoing[parent.target_variable_id], key=lambda item: item.edge_id):
            if parent.units != edge.source_unit:
                raise ValueError("network propagation source effect has an unsupported unit")
            gross_effect = parent.net_effect * edge.multiplier
            contribution = EffectContribution(
                contribution_id=f"{parent.contribution_id}:{edge.edge_id}",
                simulation_id=root.simulation_id,
                path_id=edge.path_id,
                source_intervention_id=root.source_intervention_id,
                target_variable_id=edge.target_variable_id,
                mechanism_model_id=edge.mechanism_model_id,
                gross_effect=gross_effect,
                overlap_adjustment=edge.overlap_adjustment,
                net_effect=gross_effect + edge.overlap_adjustment,
                units=edge.target_unit,
                time_step=parent.time_step + edge.lag_steps,
                parent_contribution_ids=(parent.contribution_id,),
            )
            target_step = (
                contribution.target_variable_id,
                contribution.units,
                contribution.time_step,
            )
            if target_step in target_steps:
                raise ValueError("network propagation would double count one target at one step")
            target_steps.add(target_step)
            contributions.append(contribution)
            pending.append(contribution)
    reconciliations = _reconciliations(contributions)
    return EffectContributionLedger(
        simulation_id=root.simulation_id,
        contributions=tuple(contributions),
        target_reconciliations=reconciliations,
    ).sealed()


def solve_feedback(
    initial_values: tuple[FeedbackVariable, ...],
    rules: tuple[FeedbackRule, ...],
    policy: FeedbackConvergencePolicy,
) -> FeedbackSolveResult:
    """Solve declared feedback by damped fixed point, or fail when its budget is exhausted."""
    values = tuple(
        FeedbackVariable.model_validate(value.model_dump(mode="json")) for value in initial_values
    )
    validated_rules = tuple(
        FeedbackRule.model_validate(rule.model_dump(mode="json")) for rule in rules
    )
    validated_policy = FeedbackConvergencePolicy.model_validate(policy.model_dump(mode="json"))
    if (
        any(value.content_hash is None for value in values)
        or any(rule.content_hash is None for rule in validated_rules)
        or validated_policy.content_hash is None
    ):
        raise ValueError("feedback solver requires sealed values, rules, and policy")
    by_id = {value.variable_id: value for value in values}
    if len(by_id) != len(values):
        raise ValueError("feedback solver variable IDs must be unique")
    rule_ids = [rule.rule_id for rule in validated_rules]
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("feedback solver rule IDs must be unique")
    for rule in validated_rules:
        source = by_id.get(rule.source_variable_id)
        target = by_id.get(rule.target_variable_id)
        if source is None or target is None or source.unit != rule.unit or target.unit != rule.unit:
            raise ValueError("feedback solver rule has unsupported variables or units")
    baseline = {variable.variable_id: variable.value for variable in values}
    current = dict(baseline)
    for iteration in range(1, validated_policy.max_iterations + 1):
        proposed = dict(baseline)
        for rule in sorted(validated_rules, key=lambda item: item.rule_id):
            proposed[rule.target_variable_id] += current[rule.source_variable_id] * rule.multiplier
        updated = {
            variable_id: current[variable_id]
            + validated_policy.damping * (proposed[variable_id] - current[variable_id])
            for variable_id in current
        }
        maximum_change = max(abs(updated[key] - current[key]) for key in current)
        current = updated
        if maximum_change <= validated_policy.tolerance:
            result_values = tuple(
                FeedbackVariable(
                    variable_id=variable.variable_id,
                    value=current[variable.variable_id],
                    unit=variable.unit,
                ).sealed()
                for variable in sorted(values, key=lambda item: item.variable_id)
            )
            return FeedbackSolveResult(
                policy_hash=validated_policy.content_hash,
                policy=validated_policy,
                values=result_values,
                iterations=iteration,
            ).sealed()
    raise ValueError("feedback solver did not converge within its declared iteration budget")


def _reconciliations(
    contributions: list[EffectContribution],
) -> tuple[TargetEffectReconciliation, ...]:
    grouped: dict[tuple[str, str, int], float] = defaultdict(float)
    for contribution in contributions:
        key = (contribution.target_variable_id, contribution.units, contribution.time_step)
        grouped[key] += contribution.net_effect
    return tuple(
        TargetEffectReconciliation(
            target_variable_id=target_variable_id,
            units=units,
            time_step=time_step,
            declared_simulated_total=total,
            unexplained_residual=0.0,
        )
        for (target_variable_id, units, time_step), total in sorted(grouped.items())
    )


def _has_cycle(edges: tuple[NetworkPropagationEdge, ...]) -> bool:
    outgoing: dict[str, tuple[str, ...]] = {}
    for edge in edges:
        outgoing[edge.source_variable_id] = (
            *outgoing.get(edge.source_variable_id, ()),
            edge.target_variable_id,
        )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(variable_id: str) -> bool:
        if variable_id in visiting:
            return True
        if variable_id in visited:
            return False
        visiting.add(variable_id)
        if any(visit(target) for target in outgoing.get(variable_id, ())):
            return True
        visiting.remove(variable_id)
        visited.add(variable_id)
        return False

    return any(visit(variable_id) for variable_id in outgoing)
