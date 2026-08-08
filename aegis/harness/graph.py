"""Replayable hierarchical LangGraph desk ending at verified AlphaForecasts."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from aegis.contracts import (
    AlphaForecast,
    EvidenceBundle,
    ResearchArtifact,
    ResearchCase,
    canonical_sha256,
)
from aegis.data import MarketSnapshot
from aegis.fund.models import ForecastIntegrityError, ResearchDossier, build_dossier
from aegis.harness.budgets import Budget
from aegis.harness.capability_broker import CapabilityBroker
from aegis.harness.context_compiler import compile_context
from aegis.harness.model_router import ModelProvider, ModelProviderError
from aegis.harness.network_guard import deny_network_io
from aegis.harness.skill_loader import SkillDefinition
from aegis.harness.state import DeskState
from aegis.observability import GraphEvent

_ROLE_SKILLS = {
    "coordinator": "case-plan",
    "quant": "quant-signal-analysis",
    "fundamentals": "fundamental-quality-valuation",
    "event-behavioral": "event-behavioral-reaction",
    "evidence-auditor": "evidence-contradiction-numeric-audit",
    "bull": "bull-case",
    "bear": "bear-case",
    "base-rate": "base-rate-analysis",
    "cio": "cio-synthesis",
    "verifier": "forecast-audit",
}
_SEQUENCE = {role: index for index, role in enumerate(_ROLE_SKILLS)}


class LangGraphForecastProvider:
    """The agent graph is a typed forecast provider, never a trading component."""

    network_enabled = False

    def __init__(
        self,
        model_provider: ModelProvider,
        skills: dict[str, SkillDefinition],
        evidence: EvidenceBundle,
    ) -> None:
        if model_provider.network_enabled:
            raise ValueError("replay LangGraph provider requires a network-denied model provider")
        missing = sorted(set(_ROLE_SKILLS.values()).difference(skills))
        if missing:
            raise ValueError(f"missing graph skills: {missing}")
        self.model_provider = model_provider
        self.skills = skills
        self.evidence = evidence
        self._capabilities: CapabilityBroker | None = None
        self.graph = self._build_graph()

    def _context_hash(self, state: DeskState, role: str, task: str) -> str:
        skill = self.skills[_ROLE_SKILLS[role]]
        context = compile_context(
            state["case"],
            task,
            state["snapshot"],
            state["evidence"],
            skill.metadata.allowed_tools,
            Budget(
                max_tool_calls=skill.metadata.max_tool_calls,
                max_cost_usd=skill.metadata.max_cost_usd,
            ),
        )
        return context.input_hash

    def _artifact(
        self,
        state: DeskState,
        role: str,
        artifact_type: str,
        task: str,
        extra: dict[str, Any] | None = None,
        allowed_evidence_ids: set[str] | None = None,
    ) -> tuple[ResearchArtifact, GraphEvent]:
        skill = self.skills[_ROLE_SKILLS[role]]
        input_hash = self._context_hash(state, role, task)
        warning: list[str] = []
        try:
            invocation = self.model_provider.invoke(role, skill.metadata.model_alias, input_hash)
            output = invocation.output
            actual_model = invocation.actual_model
        except ModelProviderError as exc:
            output = {"abstained": True, "abstain_reason": str(exc), "evidence_ids": []}
            actual_model = "replay/error-abstention"
            warning.append(str(exc))
        payload: dict[str, Any] = {"input_hash": input_hash, "output": output}
        if extra:
            payload.update(extra)
        raw_evidence_ids = output.get("evidence_ids", [])
        evidence_ids = (
            sorted({str(value) for value in raw_evidence_ids})
            if isinstance(raw_evidence_ids, list)
            else []
        )
        allowed_ids = allowed_evidence_ids
        if allowed_ids is None:
            allowed_ids = {record.evidence_id for record in state["evidence"].records}
        if not set(evidence_ids).issubset(allowed_ids):
            raise ForecastIntegrityError(f"{role} returned evidence outside the approved bundle")
        artifact = ResearchArtifact(
            artifact_id=f"{state['case'].case_id}:{role}",
            case_id=state["case"].case_id,
            artifact_type=artifact_type,
            producer_agent=role,
            model_alias=skill.metadata.model_alias,
            actual_model=actual_model,
            skill_versions=[skill.version_id],
            evidence_ids=evidence_ids,
            payload=payload,
            warnings=warning,
            content_hash=canonical_sha256(payload),
        )
        event = GraphEvent(
            event_id=f"{state['case'].case_id}:{role}:complete",
            case_id=state["case"].case_id,
            sequence=_SEQUENCE[role],
            node=role,
            event_type="node_complete",
            status="abstained" if warning else "completed",
            occurred_at=state["case"].as_of,
            metadata={"artifact_id": artifact.artifact_id, "input_hash": input_hash},
        )
        return artifact, event

    @staticmethod
    def _update(artifact: ResearchArtifact, event: GraphEvent) -> DeskState:
        return {
            "artifacts": {artifact.artifact_id: artifact},
            "events": {event.event_id: event},
        }

    def _simple_node(
        self, role: str, artifact_type: str, task: str
    ) -> Callable[[DeskState], DeskState]:
        def node(state: DeskState) -> DeskState:
            artifact, event = self._artifact(state, role, artifact_type, task)
            update = self._update(artifact, event)
            if artifact.warnings:
                update["failed_roles"] = frozenset({role})
            return update

        return node

    def _coordinator(self, state: DeskState) -> DeskState:
        artifact, event = self._artifact(
            state,
            "coordinator",
            "case_plan",
            "Plan the smallest sufficient desk.",
        )
        update = self._update(artifact, event)
        if artifact.warnings:
            update["failed_roles"] = frozenset({"coordinator"})
        return update

    def _audit(self, state: DeskState) -> DeskState:
        specialist_ids = [
            f"{state['case'].case_id}:{role}"
            for role in ("quant", "fundamentals", "event-behavioral")
        ]
        audited_hash = canonical_sha256(
            {
                "artifacts": [state["artifacts"][key].content_hash for key in specialist_ids],
                "evidence": state["evidence"],
            }
        )
        artifact, event = self._artifact(
            state,
            "evidence-auditor",
            "evidence_audit",
            "Audit specialist evidence, contradictions, and numeric provenance.",
            {"audited_bundle_hash": audited_hash},
        )
        output = artifact.payload.get("output")
        update = self._update(artifact, event)
        if artifact.warnings:
            update["failed_roles"] = frozenset({"evidence-auditor"})
            update["approved_evidence_ids"] = ()
            return update
        if not isinstance(output, dict) or output.get("approved") is not True:
            raise ForecastIntegrityError("evidence auditor blocked the case")
        raw_approved = output.get("evidence_ids")
        if not isinstance(raw_approved, list):
            raise ForecastIntegrityError("evidence auditor omitted approved evidence IDs")
        approved_ids = tuple(sorted({str(value) for value in raw_approved}))
        bundle_ids = {record.evidence_id for record in state["evidence"].records}
        if not set(approved_ids).issubset(bundle_ids):
            raise ForecastIntegrityError("evidence auditor approved evidence outside the bundle")
        update["approved_evidence_ids"] = approved_ids
        return update

    def _review_node(self, role: str) -> Callable[[DeskState], DeskState]:
        def node(state: DeskState) -> DeskState:
            audit_id = f"{state['case'].case_id}:evidence-auditor"
            opening_input_hash = canonical_sha256(
                {
                    "audit": state["artifacts"][audit_id].content_hash,
                    "specialists": [
                        state["artifacts"][f"{state['case'].case_id}:{name}"].content_hash
                        for name in ("quant", "fundamentals", "event-behavioral")
                    ],
                }
            )
            approved_ids = set(state.get("approved_evidence_ids", ()))
            if "evidence-auditor" in state.get("failed_roles", frozenset()):
                approved_ids = {record.evidence_id for record in state["evidence"].records}
            artifact, event = self._artifact(
                state,
                role,
                f"{role}_opening_memo",
                f"Produce the independent {role} opening memo.",
                {"opening_input_hash": opening_input_hash},
                approved_ids,
            )
            update = self._update(artifact, event)
            if artifact.warnings:
                update["failed_roles"] = frozenset({role})
            return update

        return node

    def _cio(self, state: DeskState) -> DeskState:
        synthesis_hash = canonical_sha256(
            {
                key: artifact.content_hash
                for key, artifact in sorted(state["artifacts"].items())
                if artifact.producer_agent != "coordinator"
            }
        )
        approved_ids = set(state.get("approved_evidence_ids", ()))
        if "evidence-auditor" in state.get("failed_roles", frozenset()):
            approved_ids = {record.evidence_id for record in state["evidence"].records}
        artifact, event = self._artifact(
            state,
            "cio",
            "cio_synthesis",
            "Synthesize only approved artifacts into AlphaForecasts.",
            {"synthesis_input_hash": synthesis_hash},
            approved_ids,
        )
        failed_roles = set(state.get("failed_roles", frozenset()))
        if artifact.warnings:
            failed_roles.add("cio")
        forecasts: tuple[AlphaForecast, ...] = ()
        output = artifact.payload.get("output")
        if not failed_roles and isinstance(output, dict):
            raw_forecasts = output.get("forecasts")
            if isinstance(raw_forecasts, list):
                try:
                    forecasts = tuple(
                        AlphaForecast.model_validate_json(json.dumps(item, sort_keys=True))
                        for item in raw_forecasts
                    )
                except Exception:
                    failed_roles.add("cio")
        if not forecasts:
            failed_roles.add("cio")
        if failed_roles:
            forecasts = self._blank_abstentions(state["case"], "research model stage failed")
            status = "synthesized_abstention"
        else:
            status = "synthesized"
        return {
            **self._update(artifact, event),
            "failed_roles": frozenset(failed_roles),
            "forecasts": forecasts,
            "status": status,
        }

    def _verifier(self, state: DeskState) -> DeskState:
        allowed_ids = set(state.get("approved_evidence_ids", ()))
        if "evidence-auditor" in state.get("failed_roles", frozenset()):
            allowed_ids = {record.evidence_id for record in state["evidence"].records}
        forecasts = state.get("forecasts", ())
        valid = (
            {forecast.ticker for forecast in forecasts} == set(state["case"].tickers)
            and all(forecast.as_of == state["case"].as_of for forecast in forecasts)
            and all(forecast.horizon_days == state["case"].horizon_days for forecast in forecasts)
            and all(
                forecast.abstained or set(forecast.evidence_ids).issubset(allowed_ids)
                for forecast in forecasts
            )
        )
        artifact, event = self._artifact(
            state,
            "verifier",
            "forecast_verification",
            "Verify forecast schema, evidence coverage, horizon, and numeric coherence.",
            {"deterministic_checks_passed": valid},
            allowed_ids,
        )
        output = artifact.payload.get("output")
        provider_passed = isinstance(output, dict) and output.get("passed") is True
        if not valid or not provider_passed:
            forecasts = tuple(
                self._abstain(forecast, "forecast verifier rejected synthesis")
                for forecast in forecasts
            )
            status = "verifier_forced_abstention"
        else:
            status = "verified"
        return {
            **self._update(artifact, event),
            "forecasts": forecasts,
            "status": status,
        }

    @staticmethod
    def _blank_abstentions(case: ResearchCase, reason: str) -> tuple[AlphaForecast, ...]:
        return tuple(
            AlphaForecast(
                forecast_id=canonical_sha256(
                    {"case_id": case.case_id, "ticker": ticker, "reason": reason}
                )[:32],
                model_name="research-abstention-v1",
                ticker=ticker,
                as_of=case.as_of,
                horizon_days=case.horizon_days,
                expected_excess_return=None,
                expected_volatility=None,
                probability_positive=0.5,
                confidence=0.0,
                uncertainty=1.0,
                thesis="",
                evidence_ids=[],
                abstained=True,
                abstain_reason=reason,
            )
            for ticker in sorted(case.tickers)
        )

    @staticmethod
    def _abstain(forecast: AlphaForecast, reason: str) -> AlphaForecast:
        payload = forecast.model_dump()
        payload.update(
            {
                "expected_excess_return": None,
                "expected_volatility": None,
                "thesis": "",
                "evidence_ids": [],
                "abstained": True,
                "abstain_reason": reason,
            }
        )
        return AlphaForecast.model_validate(payload)

    def _build_graph(self) -> Any:
        builder = StateGraph(DeskState)
        builder.add_node("coordinator", self._coordinator)
        builder.add_node(
            "quant",
            self._simple_node(  # type: ignore[arg-type]
                "quant", "quant_assessment", "Interpret deterministic factors."
            ),
        )
        builder.add_node(
            "fundamentals",
            self._simple_node(  # type: ignore[arg-type]
                "fundamentals", "fundamental_assessment", "Assess point-in-time fundamentals."
            ),
        )
        builder.add_node(
            "event-behavioral",
            self._simple_node(  # type: ignore[arg-type]
                "event-behavioral", "event_behavioral_assessment", "Assess event reaction."
            ),
        )
        builder.add_node("evidence-auditor", self._audit)
        bull_node: Any = self._review_node("bull")
        bear_node: Any = self._review_node("bear")
        base_rate_node: Any = self._review_node("base-rate")
        builder.add_node("bull", bull_node)
        builder.add_node("bear", bear_node)
        builder.add_node("base-rate", base_rate_node)
        builder.add_node("cio", self._cio)
        builder.add_node("verifier", self._verifier)
        builder.add_edge(START, "coordinator")
        for role in ("quant", "fundamentals", "event-behavioral"):
            builder.add_edge("coordinator", role)
        builder.add_edge(["quant", "fundamentals", "event-behavioral"], "evidence-auditor")
        for role in ("bull", "bear", "base-rate"):
            builder.add_edge("evidence-auditor", role)
        builder.add_edge(["bull", "bear", "base-rate"], "cio")
        builder.add_edge("cio", "verifier")
        builder.add_edge("verifier", END)
        return builder.compile()

    def research(self, case: ResearchCase, snapshot: MarketSnapshot) -> ResearchDossier:
        if case.mode != "replay":
            raise ForecastIntegrityError("Release-1 LangGraph provider is replay-only")
        if self.evidence.case_id != case.case_id or self.evidence.as_of != case.as_of:
            raise ForecastIntegrityError("graph evidence does not match the case")
        self._capabilities = CapabilityBroker(case.mode)
        for role, skill_name in _ROLE_SKILLS.items():
            self._capabilities.register(role, self.skills[skill_name])
        initial: DeskState = {
            "case": case,
            "snapshot": snapshot,
            "evidence": self.evidence,
            "artifacts": {},
            "events": {},
            "failed_roles": frozenset(),
            "approved_evidence_ids": (),
            "forecasts": (),
            "status": "started",
        }
        with deny_network_io():
            result = cast(DeskState, self.graph.invoke(initial))
        artifacts = tuple(artifact for _, artifact in sorted(result["artifacts"].items()))
        events = tuple(
            sorted(result["events"].values(), key=lambda event: (event.sequence, event.event_id))
        )
        forecasts = tuple(sorted(result["forecasts"], key=lambda item: item.ticker))
        return build_dossier(case, self.evidence, artifacts, forecasts, events)
