"""Deterministic official-first source planning."""

from __future__ import annotations

from aegis.contracts import SourcePlan, SourceRequest, canonical_sha256

from .registry import SourceRegistry


class SourcePlanningError(ValueError):
    pass


_PRIORITY = {
    "local_snapshot": 0,
    "official_api": 1,
    "licensed_api": 2,
    "official_web": 3,
    "rss": 4,
    "social": 5,
    "community": 6,
    "crawler": 7,
    "manual_upload": 8,
}
_METHOD = {
    "local_snapshot": "local",
    "official_api": "official-api",
    "licensed_api": "licensed-api",
    "official_web": "direct-http",
    "rss": "rss",
    "social": "agent-reach",
    "community": "agent-reach",
    "crawler": "scrapling-static",
    "manual_upload": "manual-upload",
}


class SourcePlanner:
    version = "source-planner-v1"

    def __init__(self, registry: SourceRegistry) -> None:
        self.registry = registry

    def plan(self, request: SourceRequest) -> SourcePlan:
        if request.mode != "live_research":
            raise SourcePlanningError(
                f"network source acquisition is forbidden in {request.mode} mode"
            )
        eligible = [
            source
            for source in self.registry.all()
            if source.live_safe and request.information_type in source.information_types
        ]
        eligible.sort(
            key=lambda source: (
                _PRIORITY[source.source_type],
                -source.reliability_prior,
                source.source_id,
                source.version,
            )
        )
        required = 2 if request.corroboration_required else 1
        chosen = eligible[: min(request.max_sources, required)]
        if len(chosen) < required:
            raise SourcePlanningError("insufficient eligible sources for requested corroboration")
        request_id = canonical_sha256(request.model_dump(mode="json"))[:32]
        return SourcePlan(
            request_id=request_id,
            case_id=request.case_id,
            source_ids=[source.source_id for source in chosen],
            acquisition_methods=[_METHOD[source.source_type] for source in chosen],
            mode="live_research",
            as_of=request.as_of,
            planner_version=self.version,
            estimated_cost_usd=0.0,
        )
