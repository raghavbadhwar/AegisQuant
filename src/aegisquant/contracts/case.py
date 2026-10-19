"""Investment case and workflow contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import Identifier, StrictModel, require_utc


class ResearchMode(StrEnum):
    SCREEN = "screen"
    STANDARD = "standard"
    DEEP = "deep"
    EXCEPTIONAL = "exceptional"


class CasePurpose(StrEnum):
    RESEARCH = "research"
    REBALANCE = "rebalance"
    EVENT_RESPONSE = "event_response"
    STRATEGY_VALIDATION = "strategy_validation"
    PAPER_TRADE = "paper_trade"


class CaseStatus(StrEnum):
    CASE_CREATED = "CASE_CREATED"
    MANDATE_VALIDATED = "MANDATE_VALIDATED"
    DATA_SNAPSHOT_FROZEN = "DATA_SNAPSHOT_FROZEN"
    RESEARCH_DEPTH_SELECTED = "RESEARCH_DEPTH_SELECTED"
    RESEARCH_PLANNED = "RESEARCH_PLANNED"
    SPECIALISTS_DISPATCHED = "SPECIALISTS_DISPATCHED"
    EVIDENCE_AUDITED = "EVIDENCE_AUDITED"
    FORECAST_PROPOSED = "FORECAST_PROPOSED"
    FORECAST_VERIFIED = "FORECAST_VERIFIED"
    STRATEGY_VALIDATED = "STRATEGY_VALIDATED"
    PORTFOLIO_OPTIMIZED = "PORTFOLIO_OPTIMIZED"
    RISK_APPROVED = "RISK_APPROVED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    AUTO_APPROVED = "AUTO_APPROVED"
    EXECUTION_RELEASED = "EXECUTION_RELEASED"
    RECONCILED = "RECONCILED"
    OUTCOME_MATURED = "OUTCOME_MATURED"
    LEARNING_REVIEWED = "LEARNING_REVIEWED"


class InvestmentCaseRequest(StrictModel):
    strategy_id: Identifier
    instrument_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=1000)
    analysis_time: datetime
    forecast_horizon_days: int = Field(ge=1, le=3650)
    data_snapshot_id: Identifier | None = None
    portfolio_snapshot_id: Identifier | None = None
    requested_mode: ResearchMode
    maximum_cost_usd: str = Field(pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?$")
    deadline: datetime | None = None
    purpose: CasePurpose

    @field_validator("analysis_time", "deadline")
    @classmethod
    def datetimes_are_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def deadline_is_after_analysis(self) -> "InvestmentCaseRequest":
        if self.deadline is not None and self.deadline <= self.analysis_time:
            raise ValueError("deadline must be after analysis_time")
        if len(set(self.instrument_ids)) != len(self.instrument_ids):
            raise ValueError("instrument_ids must be unique")
        return self


class InvestmentCase(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    request: InvestmentCaseRequest
    status: CaseStatus
    created_at: datetime
    created_by: Identifier

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        return require_utc(value)
