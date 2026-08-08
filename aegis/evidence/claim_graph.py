"""Canonical claim-graph construction."""

from __future__ import annotations

from aegis.contracts import Claim, ClaimEdge, ClaimGraphSnapshot, NumericClaim, canonical_sha256


def build_claim_graph(
    case_id: str,
    claims: list[Claim],
    numeric_claims: list[NumericClaim],
    edges: list[ClaimEdge],
) -> ClaimGraphSnapshot:
    ordered_claims = sorted(claims, key=lambda item: item.claim_id)
    ordered_numeric = sorted(numeric_claims, key=lambda item: item.claim_id)
    ordered_edges = sorted(edges, key=lambda item: item.edge_id)
    payload = {
        "case_id": case_id,
        "claims": ordered_claims,
        "numeric_claims": ordered_numeric,
        "edges": ordered_edges,
    }
    return ClaimGraphSnapshot(
        case_id=case_id,
        claims=ordered_claims,
        numeric_claims=ordered_numeric,
        edges=ordered_edges,
        content_hash=canonical_sha256(payload),
    )
