"""Evidence-linked claim contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from ._base import ContractModel


class Claim(ContractModel):
    claim_id: Annotated[str, Field(min_length=1)]
    case_id: Annotated[str, Field(min_length=1)]
    statement: Annotated[str, Field(min_length=1)]
    claim_type: Literal["factual", "numeric", "causal", "opinion", "forecast"]
    material: bool
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["pending", "verified", "contradicted", "rejected"] = "pending"


class NumericClaim(ContractModel):
    claim_id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    value: Decimal
    unit: Annotated[str, Field(min_length=1)]
    evidence_id: Annotated[str, Field(min_length=1)]
    coordinates: Annotated[str, Field(min_length=1)]
    calculation_id: str | None = None
