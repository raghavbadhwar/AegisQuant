"""Read-only candidate scenario-impact and causal-exposure projections."""

from __future__ import annotations

from math import isfinite
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel
from aegis.reporting.traceability import RunLedgerReceiptReference


class ScenarioImpactContribution(CandidateContractModel):
    """One candidate impact allocation, never a weight, order, or risk decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contribution_id: str = Field(min_length=1)
    v3_run_id: str = Field(min_length=1)
    mechanism_id: str = Field(min_length=1)
    causal_path_id: str = Field(min_length=1)
    gross_candidate_impact: float
    overlap_adjustment: float
    net_candidate_impact: float
    unit: Literal["candidate_impact_units"] = "candidate_impact_units"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_exact_candidate_reconciliation(self) -> ScenarioImpactContribution:
        values = (
            self.gross_candidate_impact,
            self.overlap_adjustment,
            self.net_candidate_impact,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("scenario impact contribution values must be finite")
        if self.net_candidate_impact != self.gross_candidate_impact + self.overlap_adjustment:
            raise ValueError("scenario impact contribution must reconcile exactly")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("scenario impact contribution content hash mismatch")
        return self

    def sealed(self) -> ScenarioImpactContribution:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = ScenarioImpactContribution.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class PortfolioScenarioImpactReport(CandidateContractModel):
    """A sealed v4D read-only projection bound only to v3 receipt references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str = Field(min_length=1)
    portfolio_id: str = Field(min_length=1)
    as_of: AwareDatetime
    scenario_run_id: str = Field(min_length=1)
    scenario_run_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    v3_run_receipts: tuple[RunLedgerReceiptReference, ...] = Field(min_length=1)
    contributions: tuple[ScenarioImpactContribution, ...] = Field(min_length=1)
    declared_net_candidate_impact: float
    unit: Literal["candidate_impact_units"] = "candidate_impact_units"
    release_disposition: Literal["release_gated"] = "release_gated"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_read_only_and_reconciled_to_v3_receipts(self) -> PortfolioScenarioImpactReport:
        receipts = tuple(
            RunLedgerReceiptReference.model_validate(receipt.model_dump(mode="json"))
            for receipt in self.v3_run_receipts
        )
        contributions = tuple(
            ScenarioImpactContribution.model_validate(contribution.model_dump(mode="json"))
            for contribution in self.contributions
        )
        if any(receipt.as_of > self.as_of for receipt in receipts):
            raise ValueError("portfolio scenario receipt cannot be after the report cutoff")
        run_ids = [receipt.run_id for receipt in receipts]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("portfolio scenario receipt run IDs must be unique")
        if any(contribution.content_hash is None for contribution in contributions):
            raise ValueError("portfolio scenario impact requires sealed contributions")
        contribution_ids = [contribution.contribution_id for contribution in contributions]
        if len(contribution_ids) != len(set(contribution_ids)):
            raise ValueError("portfolio scenario contribution IDs must be unique")
        economic_paths = [
            (contribution.v3_run_id, contribution.mechanism_id, contribution.causal_path_id)
            for contribution in contributions
        ]
        if len(economic_paths) != len(set(economic_paths)):
            raise ValueError("portfolio scenario economic paths must not be double counted")
        contribution_run_ids = {contribution.v3_run_id for contribution in contributions}
        if contribution_run_ids != set(run_ids):
            raise ValueError(
                "portfolio scenario contributions must exactly bind listed v3 receipts"
            )
        if not isfinite(self.declared_net_candidate_impact):
            raise ValueError("portfolio scenario declared impact must be finite")
        if self.declared_net_candidate_impact != sum(
            contribution.net_candidate_impact for contribution in contributions
        ):
            raise ValueError("portfolio scenario impact must reconcile exactly to contributions")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("portfolio scenario impact content hash mismatch")
        return self

    def sealed(self) -> PortfolioScenarioImpactReport:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = PortfolioScenarioImpactReport.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class CausalPathExposure(CandidateContractModel):
    """One non-negative candidate causal exposure derived from receipt-bound impacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mechanism_id: str = Field(min_length=1)
    causal_path_id: str = Field(min_length=1)
    v3_run_ids: tuple[str, ...] = Field(min_length=1)
    candidate_exposure_units: float = Field(ge=0.0)
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_unique_finite_receipt_scope(self) -> CausalPathExposure:
        if not isfinite(self.candidate_exposure_units):
            raise ValueError("causal exposure units must be finite")
        if any(not run_id for run_id in self.v3_run_ids) or len(self.v3_run_ids) != len(
            set(self.v3_run_ids)
        ):
            raise ValueError("causal exposure v3 run IDs must be nonempty and unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("causal exposure content hash mismatch")
        return self

    def sealed(self) -> CausalPathExposure:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = CausalPathExposure.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class CausalExposureReport(CandidateContractModel):
    """Read-only mechanism concentration view derived exactly from candidate impacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str = Field(min_length=1)
    portfolio_id: str = Field(min_length=1)
    impact_report: PortfolioScenarioImpactReport
    exposures: tuple[CausalPathExposure, ...] = Field(min_length=1)
    total_candidate_exposure_units: float = Field(ge=0.0)
    release_disposition: Literal["release_gated"] = "release_gated"
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exactly_derives_each_causal_path_once(self) -> CausalExposureReport:
        impact = PortfolioScenarioImpactReport.model_validate(
            self.impact_report.model_dump(mode="json")
        )
        exposures = tuple(
            CausalPathExposure.model_validate(exposure.model_dump(mode="json"))
            for exposure in self.exposures
        )
        if impact.content_hash is None or any(
            exposure.content_hash is None for exposure in exposures
        ):
            raise ValueError("causal exposure report requires sealed impact and exposure inputs")
        if self.portfolio_id != impact.portfolio_id:
            raise ValueError("causal exposure report portfolio does not match its impact report")
        expected_values: dict[tuple[str, str], float] = {}
        expected_run_ids: dict[tuple[str, str], set[str]] = {}
        for contribution in impact.contributions:
            key = (contribution.mechanism_id, contribution.causal_path_id)
            expected_values[key] = expected_values.get(key, 0.0) + contribution.net_candidate_impact
            expected_run_ids.setdefault(key, set()).add(contribution.v3_run_id)
        exposure_by_key = {(item.mechanism_id, item.causal_path_id): item for item in exposures}
        if len(exposure_by_key) != len(exposures) or set(exposure_by_key) != set(expected_values):
            raise ValueError("causal exposure report must include every causal path exactly once")
        for key, exposure in exposure_by_key.items():
            if exposure.candidate_exposure_units != abs(expected_values[key]) or (
                exposure.v3_run_ids != tuple(sorted(expected_run_ids[key]))
            ):
                raise ValueError("causal exposure report values do not reconcile to impacts")
        total = sum(item.candidate_exposure_units for item in exposures)
        if (
            not isfinite(self.total_candidate_exposure_units)
            or self.total_candidate_exposure_units != total
        ):
            raise ValueError("causal exposure report total must reconcile exactly")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("causal exposure report content hash mismatch")
        return self

    def sealed(self) -> CausalExposureReport:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = CausalExposureReport.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def derive_causal_exposure_report(
    report_id: str, impact_report: PortfolioScenarioImpactReport
) -> CausalExposureReport:
    """Create the candidate concentration view without reading or modifying v3 records."""
    impact = PortfolioScenarioImpactReport.model_validate(impact_report.model_dump(mode="json"))
    if impact.content_hash is None:
        raise ValueError("causal exposure derivation requires a sealed impact report")
    values: dict[tuple[str, str], float] = {}
    run_ids: dict[tuple[str, str], set[str]] = {}
    for contribution in impact.contributions:
        key = (contribution.mechanism_id, contribution.causal_path_id)
        values[key] = values.get(key, 0.0) + contribution.net_candidate_impact
        run_ids.setdefault(key, set()).add(contribution.v3_run_id)
    exposures = tuple(
        CausalPathExposure(
            mechanism_id=mechanism_id,
            causal_path_id=path_id,
            v3_run_ids=tuple(sorted(run_ids[(mechanism_id, path_id)])),
            candidate_exposure_units=abs(values[(mechanism_id, path_id)]),
        ).sealed()
        for mechanism_id, path_id in sorted(values)
    )
    return CausalExposureReport(
        report_id=report_id,
        portfolio_id=impact.portfolio_id,
        impact_report=impact,
        exposures=exposures,
        total_candidate_exposure_units=sum(
            exposure.candidate_exposure_units for exposure in exposures
        ),
    ).sealed()
