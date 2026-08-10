"""Fail-closed identification service for candidate causal edges."""

from __future__ import annotations

from .adapters import CausalToolAbstention, CausalToolAdapter
from .contracts import (
    CausalGraphSnapshot,
    IdentificationOutcome,
    IdentificationRecord,
    IdentificationRequest,
    IdentificationStatus,
)


class CausalIdentificationService:
    def __init__(self, adapter: CausalToolAdapter) -> None:
        self._adapter = adapter

    @staticmethod
    def _safe_attribute(value: object, name: str, fallback: object = None) -> object:
        try:
            return getattr(value, name, fallback)
        except Exception:
            return fallback

    @staticmethod
    def _abstain(
        request: object, status: IdentificationStatus, reason: str
    ) -> IdentificationOutcome:
        request_id = CausalIdentificationService._safe_attribute(
            request, "request_id", "invalid-identification-request"
        )
        edge_id = CausalIdentificationService._safe_attribute(
            request, "edge_id", "invalid-causal-edge"
        )
        graph = CausalIdentificationService._safe_attribute(request, "causal_graph")
        graph_hash = CausalIdentificationService._safe_attribute(graph, "content_hash")
        return IdentificationOutcome(
            request_id=(
                request_id if isinstance(request_id, str) and request_id else "invalid-request"
            ),
            edge_id=(edge_id if isinstance(edge_id, str) and edge_id else "invalid-causal-edge"),
            status=status,
            reason=reason,
            causal_graph_hash=graph_hash if isinstance(graph_hash, str) else None,
        )

    def identify(self, request: IdentificationRequest) -> IdentificationOutcome:
        """Validate all bindings, invoke one optional tool, and never mutate the graph."""
        try:
            candidate = IdentificationRequest.model_validate(
                request.model_dump(mode="json", warnings=False)
            )
            graph = CausalGraphSnapshot.model_validate(
                candidate.causal_graph.model_dump(mode="json")
            )
        except (AttributeError, ValueError):
            return self._abstain(
                request, IdentificationStatus.NOT_IDENTIFIED, "identification request is invalid"
            )
        if graph.content_hash is None:
            return self._abstain(
                candidate,
                IdentificationStatus.NOT_IDENTIFIED,
                "causal graph must be sealed before identification",
            )
        edge = {item.edge_id: item for item in graph.eligible_edges()}.get(candidate.edge_id)
        if edge is None:
            return self._abstain(
                candidate,
                IdentificationStatus.NOT_IDENTIFIED,
                "causal edge is absent or ineligible at the graph cutoff",
            )
        omitted_confounders = set(edge.confounder_ids).difference(candidate.adjustment_set)
        if omitted_confounders:
            return self._abstain(
                candidate,
                IdentificationStatus.NOT_IDENTIFIED,
                "adjustment set omits declared confounder: "
                f"{', '.join(sorted(omitted_confounders))}",
            )
        if (
            set(candidate.evidence_ids) != set(edge.evidence_ids)
            or not set(candidate.evidence_ids).issubset(graph.evidence_ids)
            or set(candidate.assumption_ids) != set(edge.assumption_ids)
        ):
            return self._abstain(
                candidate,
                IdentificationStatus.NOT_IDENTIFIED,
                "identification evidence or assumptions do not bind the candidate edge",
            )
        try:
            raw_record = self._adapter.identify(candidate)
        except CausalToolAbstention as exc:
            return self._abstain(candidate, exc.status, exc.reason)
        except Exception as exc:
            return self._abstain(
                candidate,
                IdentificationStatus.NOT_IDENTIFIED,
                f"causal tool failed closed: {type(exc).__name__}",
            )
        try:
            record = IdentificationRecord.model_validate(raw_record.model_dump(mode="json"))
        except (AttributeError, ValueError):
            return self._abstain(
                candidate,
                IdentificationStatus.NOT_IDENTIFIED,
                "causal tool returned an invalid identification record",
            )
        if (
            record.method != candidate.method
            or record.adjustment_set != candidate.adjustment_set
            or set(record.assumption_ids) != set(candidate.assumption_ids)
            or set(record.evidence_ids) != set(candidate.evidence_ids)
            or {item.method for item in record.refutations} != set(candidate.refutation_methods)
            or record.validated_at > graph.as_of
            or any(item.evaluated_at > graph.as_of for item in record.refutations)
        ):
            return self._abstain(
                candidate,
                IdentificationStatus.NOT_IDENTIFIED,
                "causal tool result does not bind the request or point-in-time graph",
            )
        return IdentificationOutcome(
            request_id=candidate.request_id,
            edge_id=candidate.edge_id,
            status=IdentificationStatus.IDENTIFIED,
            reason="Identification and declared refutations passed for candidate review only.",
            causal_graph_hash=graph.content_hash,
            identification=record,
        )
