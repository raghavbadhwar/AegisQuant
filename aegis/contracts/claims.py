"""Evidence-linked claim contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ._base import ContractModel
from .artifacts import canonical_sha256


class Claim(ContractModel):
    claim_id: Annotated[str, Field(min_length=1)]
    case_id: Annotated[str, Field(min_length=1)]
    statement: Annotated[str, Field(min_length=1)]
    claim_type: Literal["factual", "numeric", "causal", "opinion", "forecast"]
    material: bool
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["pending", "verified", "contradicted", "rejected"] = "pending"

    @model_validator(mode="after")
    def material_claims_require_provenance(self) -> Claim:
        if self.material and not self.evidence_ids:
            raise ValueError("material claims require evidence provenance")
        return self


class NumericClaim(ContractModel):
    claim_id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    value: Decimal
    unit: Annotated[str, Field(min_length=1)]
    evidence_id: Annotated[str, Field(min_length=1)]
    coordinates: Annotated[str, Field(min_length=1)]
    calculation_id: str | None = None


GraphNodeKind = Literal[
    "evidence", "claim", "calculation", "artifact", "forecast", "portfolio_decision", "outcome"
]
ClaimRelation = Literal["SUPPORTS", "CONTRADICTS", "DERIVED_BY", "USED_IN", "LED_TO"]

_ALLOWED_EDGE_TYPES = {
    ("evidence", "SUPPORTS", "claim"),
    ("evidence", "CONTRADICTS", "claim"),
    ("claim", "DERIVED_BY", "calculation"),
    ("claim", "USED_IN", "artifact"),
    ("artifact", "USED_IN", "forecast"),
    ("forecast", "LED_TO", "portfolio_decision"),
    ("portfolio_decision", "LED_TO", "outcome"),
}


class ClaimEdge(ContractModel):
    edge_id: Annotated[str, Field(min_length=1)]
    source_kind: GraphNodeKind
    source_id: Annotated[str, Field(min_length=1)]
    relation: ClaimRelation
    target_kind: GraphNodeKind
    target_id: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def legal_edge_type(self) -> ClaimEdge:
        if (self.source_kind, self.relation, self.target_kind) not in _ALLOWED_EDGE_TYPES:
            raise ValueError("illegal claim-graph edge type")
        return self


class ClaimGraphSnapshot(ContractModel):
    case_id: Annotated[str, Field(min_length=1)]
    claims: list[Claim] = Field(default_factory=list)
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    edges: list[ClaimEdge] = Field(default_factory=list)
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def graph_is_closed_and_hashed(self) -> ClaimGraphSnapshot:
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim IDs must be unique")
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("claim edge IDs must be unique")
        if any(
            (edge.target_kind == "claim" and edge.target_id not in claim_ids)
            or (edge.source_kind == "claim" and edge.source_id not in claim_ids)
            for edge in self.edges
        ):
            raise ValueError("claim graph contains an unknown claim endpoint")
        payload = {
            "case_id": self.case_id,
            "claims": self.claims,
            "numeric_claims": self.numeric_claims,
            "edges": self.edges,
        }
        if self.content_hash != canonical_sha256(payload):
            raise ValueError("claim graph content hash mismatch")
        return self
