"""Candidate-only, append-linked world-model experiment contracts."""

from __future__ import annotations

from enum import StrEnum
from itertools import pairwise

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel


class TemporalSplitKind(StrEnum):
    DEVELOPMENT = "development"
    CALIBRATION = "calibration"
    SCENARIO_VALIDATION = "scenario_validation"
    FINAL_HOLDOUT = "final_holdout"


class ExperimentStatus(StrEnum):
    DECLARED = "declared"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    NEUTRAL = "neutral"


class ModelRiskTier(StrEnum):
    TIER_0 = "tier_0"
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class TemporalSplit(CandidateContractModel):
    """One immutable chronological evaluation interval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TemporalSplitKind
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def has_positive_duration(self) -> TemporalSplit:
        if self.ends_at <= self.starts_at:
            raise ValueError("temporal split must have positive duration")
        return self


class TemporalEvaluationPlan(CandidateContractModel):
    """Declared chronological splits, including a human-locked final holdout."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    development: TemporalSplit
    calibration: TemporalSplit
    scenario_validation: TemporalSplit
    final_holdout: TemporalSplit

    @model_validator(mode="after")
    def has_ordered_immutable_splits(self) -> TemporalEvaluationPlan:
        ordered = (
            (self.development, TemporalSplitKind.DEVELOPMENT),
            (self.calibration, TemporalSplitKind.CALIBRATION),
            (self.scenario_validation, TemporalSplitKind.SCENARIO_VALIDATION),
            (self.final_holdout, TemporalSplitKind.FINAL_HOLDOUT),
        )
        if any(split.kind != expected_kind for split, expected_kind in ordered):
            raise ValueError("temporal evaluation split kind does not match its declared role")
        if any(later.starts_at < earlier.ends_at for (earlier, _), (later, _) in pairwise(ordered)):
            raise ValueError("temporal evaluation splits must be chronological and non-overlapping")
        return self


class WorldModelExperimentManifest(CandidateContractModel):
    """Immutable candidate experiment entry with no execution or promotion authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: str = Field(min_length=1)
    parent_experiment_id: str | None = Field(default=None, min_length=1)
    manifest_sequence: int = Field(default=1, ge=1)
    previous_manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    declared_hypothesis: str = Field(min_length=1)
    declared_before_run: bool
    declared_at: AwareDatetime
    run_started_at: AwareDatetime | None = None
    run_completed_at: AwareDatetime | None = None

    causal_graph_version: str = Field(min_length=1)
    mechanism_versions: tuple[tuple[str, str], ...] = Field(min_length=1)
    twin_versions: tuple[tuple[str, str], ...] = Field(min_length=1)
    domain_pack_version: str = Field(min_length=1)

    data_snapshot_id: str = Field(min_length=1)
    belief_state_id: str = Field(min_length=1)
    scenario_ids: tuple[str, ...] = Field(min_length=1)
    parameter_changes: tuple[tuple[str, str], ...] = ()
    code_commit: str = Field(min_length=1)
    container_digest: str = Field(min_length=1)
    random_seeds: tuple[int, ...] = Field(min_length=1)

    temporal_evaluation: TemporalEvaluationPlan
    scenario_validation_attempt: int = Field(default=0, ge=0, le=1)
    development_metrics: tuple[object, ...] = ()
    calibration_metrics: tuple[object, ...] = ()
    validation_metrics: tuple[object, ...] = ()
    holdout_metrics: tuple[object, ...] = ()
    holdout_unlock_id: str | None = Field(default=None, min_length=1)

    author_id: str = Field(min_length=1)
    status: ExperimentStatus
    model_risk_tier: ModelRiskTier
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def model_risk_is_capped(self) -> WorldModelExperimentManifest:
        if self.model_risk_tier == ModelRiskTier.TIER_3:
            raise ValueError("world-model experiments are capped at Tier 2")
        if not self.declared_before_run:
            raise ValueError("world-model experiment must be declared before run")
        if self.status == ExperimentStatus.DECLARED and (
            self.run_started_at is not None or self.run_completed_at is not None
        ):
            raise ValueError("declared status cannot contain run timestamps")
        if self.status == ExperimentStatus.RUNNING and (
            self.run_started_at is None or self.run_completed_at is not None
        ):
            raise ValueError(
                "running status requires a start timestamp and no completion timestamp"
            )
        if self.status in {
            ExperimentStatus.COMPLETED,
            ExperimentStatus.FAILED,
            ExperimentStatus.NEUTRAL,
        } and (self.run_started_at is None or self.run_completed_at is None):
            raise ValueError("terminal status requires complete lifecycle timestamps")
        if self.run_started_at is not None and self.run_started_at < self.declared_at:
            raise ValueError("world-model experiment cannot start before declaration")
        if (
            self.run_completed_at is not None
            and self.run_started_at is not None
            and (self.run_completed_at < self.run_started_at)
        ):
            raise ValueError("world-model experiment cannot complete before it starts")
        if self.manifest_sequence == 1 and (
            self.parent_experiment_id is not None or self.previous_manifest_hash is not None
        ):
            raise ValueError("first manifest cannot carry an append link")
        if self.manifest_sequence > 1 and (
            self.parent_experiment_id is None or self.previous_manifest_hash is None
        ):
            raise ValueError("later manifest requires a complete append link")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("world-model experiment content hash mismatch")
        return self

    def sealed(self) -> WorldModelExperimentManifest:
        """Return the deterministic, content-addressed candidate experiment manifest."""
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = WorldModelExperimentManifest.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class WorldModelExperimentLedger(CandidateContractModel):
    """Content-addressed experiment history, not an authenticated ledger or authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifests: tuple[WorldModelExperimentManifest, ...] = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_verified_predecessor_chain(self) -> WorldModelExperimentLedger:
        manifests = tuple(
            WorldModelExperimentManifest.model_validate(manifest.model_dump(mode="json"))
            for manifest in self.manifests
        )
        experiment_ids = [manifest.experiment_id for manifest in manifests]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("world-model experiment ledger IDs must be unique")
        if manifests[0].manifest_sequence != 1:
            raise ValueError("world-model experiment ledger must begin with a single root")
        for predecessor, manifest in pairwise(manifests):
            if manifest.manifest_sequence != predecessor.manifest_sequence + 1:
                raise ValueError(
                    "world-model experiment ledger must preserve a single root sequence"
                )
            if manifest.parent_experiment_id != predecessor.experiment_id:
                raise ValueError(
                    "world-model experiment ledger predecessor is absent or inconsistent"
                )
            if predecessor.content_hash is None:
                raise ValueError("world-model experiment ledger predecessor is unsealed")
            if manifest.previous_manifest_hash != predecessor.content_hash:
                raise ValueError("world-model experiment ledger predecessor hash is inconsistent")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("world-model experiment ledger content hash mismatch")
        return self

    def sealed(self) -> WorldModelExperimentLedger:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = WorldModelExperimentLedger.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})

    def append(self, manifest: WorldModelExperimentManifest) -> WorldModelExperimentLedger:
        """Validate and append one exact successor without replacing prior history."""
        validated = WorldModelExperimentLedger.model_validate(self.model_dump(mode="json"))
        if validated.content_hash is None:
            raise ValueError("world-model experiment ledger must be sealed before appending")
        return WorldModelExperimentLedger(manifests=(*validated.manifests, manifest)).sealed()
