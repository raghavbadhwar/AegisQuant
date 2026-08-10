"""Pure candidate-only causal graph inspection view."""

from __future__ import annotations

from .contracts import (
    CausalEdge,
    CausalEdgeKind,
    CausalGraphSnapshot,
    CausalSupportLevel,
    EdgeStatus,
)


def _identification_label(edge: CausalEdge, eligible: bool) -> str:
    if (
        eligible
        and edge.kind in {CausalEdgeKind.IDENTIFIED_CAUSE, CausalEdgeKind.STRUCTURAL_MECHANISM}
        and edge.support_level
        in {CausalSupportLevel.C2_IDENTIFIED, CausalSupportLevel.C3_STRUCTURAL}
        and edge.status in {EdgeStatus.SUPPORTED, EdgeStatus.VALIDATED_FOR_DOMAIN}
        and edge.identification is not None
    ):
        return "identified_candidate"
    return "not_identified"


def causal_graph_view(graph: CausalGraphSnapshot) -> dict[str, object]:
    """Render a sealed graph without elevating any candidate to factual authority."""
    try:
        validated = CausalGraphSnapshot.model_validate(graph.model_dump(mode="json"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("causal graph inspection requires a valid graph") from exc
    if validated.content_hash is None:
        raise ValueError("causal graph inspection requires a sealed graph")

    eligible_edge_ids = {edge.edge_id for edge in validated.eligible_edges()}
    return {
        "authority": "candidate_only",
        "snapshot_id": validated.snapshot_id,
        "graph_version": validated.graph_version,
        "content_hash": validated.content_hash,
        "edges": tuple(
            {
                "edge_id": edge.edge_id,
                "kind": edge.kind.value,
                "status": edge.status.value,
                "support_level": edge.support_level.value,
                "identification": _identification_label(edge, edge.edge_id in eligible_edge_ids),
            }
            for edge in sorted(validated.edges, key=lambda item: item.edge_id)
        ),
    }
