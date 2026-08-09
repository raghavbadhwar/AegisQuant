"""Sealed local fundamental golden-case fixture loader."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import AwareDatetime, Field

from aegis.contracts import (
    CompanyResearchRequest,
    EvidenceBundle,
    FilingFact,
    ForecastCalibrationRecord,
    ForecastDriver,
    GuidanceRecord,
    PeerMultiple,
    RawFilingSnapshot,
)
from aegis.contracts._base import ContractModel

from .hashing import build_hashed
from .normalization import raw_snapshot
from .service import FundamentalResearchInputs


class FundamentalFixture(ContractModel):
    case_id: str
    request: CompanyResearchRequest
    inputs_available_at: AwareDatetime
    source_receipt_ids: list[str] = Field(min_length=1)
    evidence: EvidenceBundle
    field_evidence: dict[str, list[str]] = Field(min_length=1)
    sector: str
    industry: str
    market_price: Decimal = Field(gt=0, allow_inf_nan=False)
    discount_rate: float = Field(gt=0, lt=1, allow_inf_nan=False)
    terminal_growth_by_scenario: dict[str, float]
    terminal_roic_by_scenario: dict[str, float]
    scenario_probabilities: dict[str, float]
    facts: list[FilingFact] = Field(min_length=1)
    raw_receipt_ids: list[str] = Field(min_length=1)
    source_manifest_versions: dict[str, str] = Field(min_length=1)
    drivers: list[ForecastDriver] = Field(min_length=1)
    peers: list[PeerMultiple] = Field(min_length=2)
    guidance: list[GuidanceRecord] = Field(default_factory=list)
    revenue_driver_descriptions: list[str] = Field(min_length=1)
    competitors: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(min_length=1)
    subscription_revenue_share: float = Field(ge=0, le=1)
    profitable: bool
    expected_volatility: float = Field(gt=0, allow_inf_nan=False)
    calibration: ForecastCalibrationRecord


def load_fundamental_fixture(
    path: str | Path,
) -> tuple[CompanyResearchRequest, RawFilingSnapshot, FundamentalResearchInputs]:
    fixture = FundamentalFixture.model_validate_json(Path(path).read_text())
    snapshot = raw_snapshot(
        snapshot_id=f"raw-filing-{fixture.case_id}",
        ticker=fixture.request.ticker,
        as_of=fixture.request.as_of,
        facts=fixture.facts,
        raw_receipt_ids=fixture.raw_receipt_ids,
        source_manifest_versions=fixture.source_manifest_versions,
    )
    input_values = {
        "input_snapshot_id": f"fundamental-inputs-{fixture.case_id}",
        "request_id": fixture.request.request_id,
        "ticker": fixture.request.ticker,
        "available_at": fixture.inputs_available_at,
        "source_receipt_ids": fixture.source_receipt_ids,
        "evidence": fixture.evidence,
        "field_evidence": fixture.field_evidence,
        "sector": fixture.sector,
        "industry": fixture.industry,
        "market_price": fixture.market_price,
        "discount_rate": fixture.discount_rate,
        "terminal_growth_by_scenario": fixture.terminal_growth_by_scenario,
        "terminal_roic_by_scenario": fixture.terminal_roic_by_scenario,
        "scenario_probabilities": fixture.scenario_probabilities,
        "drivers": tuple(fixture.drivers),
        "peers": tuple(fixture.peers),
        "guidance": tuple(fixture.guidance),
        "revenue_driver_descriptions": tuple(fixture.revenue_driver_descriptions),
        "competitors": tuple(fixture.competitors),
        "catalysts": tuple(fixture.catalysts),
        "risks": tuple(fixture.risks),
        "subscription_revenue_share": fixture.subscription_revenue_share,
        "profitable": fixture.profitable,
        "expected_volatility": fixture.expected_volatility,
        "calibration": fixture.calibration,
        "contract_version": "3.0.0",
    }
    inputs = build_hashed(FundamentalResearchInputs, **input_values)
    return fixture.request, snapshot, inputs
