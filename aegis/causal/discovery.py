"""Quarantined causal-discovery candidates with no promotion authority."""

from __future__ import annotations

from pydantic import AwareDatetime, ConfigDict, Field

from aegis.contracts._base import CandidateContractModel

from .contracts import CausalEdge, CausalEdgeKind, CausalSupportLevel, EdgeStatus


class CausalDiscoveryCandidate(CandidateContractModel):
    """A discovery result that can only become a draft C0 hypothesis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    discovery_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    source_variable_id: str = Field(min_length=1)
    target_variable_id: str = Field(min_length=1)
    mechanism_description: str = Field(min_length=1)
    sign: int = Field(ge=-1, le=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    domain_pack: str = Field(min_length=1)
    known_from: AwareDatetime
    confidence: float = Field(ge=0.0, le=1.0)

    def as_edge(self, edge_id: str) -> CausalEdge:
        """Materialize this candidate only as a non-authoritative draft hypothesis."""
        return CausalEdge(
            edge_id=edge_id,
            source_variable_id=self.source_variable_id,
            target_variable_id=self.target_variable_id,
            kind=CausalEdgeKind.HYPOTHESIZED_CAUSE,
            status=EdgeStatus.DRAFT,
            support_level=CausalSupportLevel.C0_NARRATIVE,
            mechanism_description=self.mechanism_description,
            sign=self.sign,
            evidence_ids=self.evidence_ids,
            domain_pack=self.domain_pack,
            known_from=self.known_from,
            confidence=self.confidence,
        )
