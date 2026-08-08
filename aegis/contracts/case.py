"""Research case contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from ._base import ContractModel, normalize_ticker

RunMode = Literal["replay", "historical", "live_research", "research_lab"]


class ResearchCase(ContractModel):
    """Immutable inputs that define a point-in-time research case."""

    case_id: Annotated[str, Field(min_length=1)]
    tickers: Annotated[list[str], Field(min_length=1)]
    as_of: AwareDatetime
    horizon_days: Annotated[int, Field(gt=0)]
    mode: RunMode
    research_question: Annotated[str, Field(min_length=1)]
    created_at: AwareDatetime

    @field_validator("tickers", mode="before")
    @classmethod
    def normalize_tickers(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        tickers = [normalize_ticker(ticker) for ticker in value]
        if len(set(tickers)) != len(tickers):
            raise ValueError("tickers must be unique")
        return tickers

    @model_validator(mode="after")
    def creation_is_not_before_case_cutoff(self) -> ResearchCase:
        if self.created_at < self.as_of:
            raise ValueError("created_at cannot be before as_of")
        return self
