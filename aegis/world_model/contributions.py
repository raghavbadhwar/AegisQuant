"""Append-only candidate-only effect-contribution ledger contracts."""

from __future__ import annotations

from math import isclose, isfinite
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel


class EffectContribution(CandidateContractModel):
    """One reconciled causal-path effect; never execution or factual authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contribution_id: str = Field(min_length=1)
    simulation_id: str = Field(min_length=1)
    path_id: str = Field(min_length=1)
    source_intervention_id: str = Field(min_length=1)
    target_variable_id: str = Field(min_length=1)
    mechanism_model_id: str = Field(min_length=1)
    gross_effect: float
    overlap_adjustment: float
    net_effect: float
    units: str = Field(min_length=1)
    time_step: int = Field(ge=0)
    parent_contribution_ids: tuple[str, ...] = ()
    authority: Literal["candidate_only"] = "candidate_only"

    @model_validator(mode="after")
    def validate_effect_reconciliation(self) -> EffectContribution:
        effects = (self.gross_effect, self.overlap_adjustment, self.net_effect)
        if not all(isfinite(effect) for effect in effects):
            raise ValueError("effect contribution values must be finite")
        if not isclose(
            self.net_effect,
            self.gross_effect + self.overlap_adjustment,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "effect contribution net effect must reconcile to gross effect plus overlap"
            )
        if self.contribution_id in self.parent_contribution_ids:
            raise ValueError("effect contribution cannot parent itself")
        if len(self.parent_contribution_ids) != len(set(self.parent_contribution_ids)):
            raise ValueError("effect contribution parent IDs must be unique")
        return self


class TargetEffectReconciliation(CandidateContractModel):
    """Declared aggregate effect and residual for one target/unit/time group."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_variable_id: str = Field(min_length=1)
    units: str = Field(min_length=1)
    time_step: int = Field(ge=0)
    aggregation_policy: Literal["sum"] = "sum"
    declared_simulated_total: float
    unexplained_residual: float

    @model_validator(mode="after")
    def has_finite_declared_totals(self) -> TargetEffectReconciliation:
        if not isfinite(self.declared_simulated_total) or not isfinite(self.unexplained_residual):
            raise ValueError("target reconciliation values must be finite")
        return self


class EffectContributionLedger(CandidateContractModel):
    """Immutable, content-addressed (not authenticated) contribution record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    simulation_id: str = Field(min_length=1)
    contributions: tuple[EffectContribution, ...]
    target_reconciliations: tuple[TargetEffectReconciliation, ...] = ()
    parent_ledger_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_ledger(self) -> EffectContributionLedger:
        contribution_ids = [contribution.contribution_id for contribution in self.contributions]
        if len(contribution_ids) != len(set(contribution_ids)):
            raise ValueError("effect contribution IDs must be unique")
        if any(
            contribution.simulation_id != self.simulation_id for contribution in self.contributions
        ):
            raise ValueError("effect contributions must share one simulation ID")
        economic_path_keys = [
            (
                contribution.path_id,
                contribution.source_intervention_id,
                contribution.target_variable_id,
                contribution.mechanism_model_id,
                contribution.units,
                contribution.time_step,
            )
            for contribution in self.contributions
        ]
        if len(economic_path_keys) != len(set(economic_path_keys)):
            raise ValueError("effect contribution economic paths must be unique")
        preceding_ids: set[str] = set()
        for contribution in self.contributions:
            if not set(contribution.parent_contribution_ids).issubset(preceding_ids):
                raise ValueError("effect contribution parents must precede their dependent entry")
            preceding_ids.add(contribution.contribution_id)
        grouped_contributions: dict[tuple[str, str, int], list[EffectContribution]] = {}
        for contribution in self.contributions:
            key = (contribution.target_variable_id, contribution.units, contribution.time_step)
            grouped_contributions.setdefault(key, []).append(contribution)
        reconciliation_by_key = {
            (
                reconciliation.target_variable_id,
                reconciliation.units,
                reconciliation.time_step,
            ): reconciliation
            for reconciliation in self.target_reconciliations
        }
        if len(reconciliation_by_key) != len(self.target_reconciliations) or set(
            reconciliation_by_key
        ) != set(grouped_contributions):
            raise ValueError(
                "target reconciliation must cover each target/unit/time contribution group"
            )
        for key, contributions in grouped_contributions.items():
            reconciliation = reconciliation_by_key[key]
            net_effect = sum(contribution.net_effect for contribution in contributions)
            if not isclose(
                net_effect + reconciliation.unexplained_residual,
                reconciliation.declared_simulated_total,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError("target reconciliation must match net effects plus residual")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("effect contribution ledger content hash mismatch")
        return self

    def sealed(self) -> EffectContributionLedger:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = EffectContributionLedger.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})

    def append(
        self,
        contribution: EffectContribution,
        target_reconciliations: tuple[TargetEffectReconciliation, ...],
    ) -> EffectContributionLedger:
        """Create a new ledger linked to this sealed immutable state."""
        validated = EffectContributionLedger.model_validate(self.model_dump(mode="json"))
        if validated.content_hash is None:
            raise ValueError("effect contribution ledger must be sealed before appending")
        return EffectContributionLedger(
            simulation_id=validated.simulation_id,
            contributions=(*validated.contributions, contribution),
            target_reconciliations=target_reconciliations,
            parent_ledger_hash=validated.content_hash,
        ).sealed()
