"""Deterministic case and graph event records."""

from __future__ import annotations

from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class GraphEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    case_id: str
    sequence: int = Field(ge=0)
    node: str
    event_type: str
    status: str
    occurred_at: AwareDatetime
    metadata: dict[str, Any] = Field(default_factory=dict)
