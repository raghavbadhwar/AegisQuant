"""Replayable hierarchical LangGraph desk ending at verified AlphaForecasts."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from aegis.contracts import (
    AlphaForecast,
    Claim,
    ClaimEdge,
    ClaimGraphSnapshot,
    EvidenceAuditPolicy,
    EvidenceBundle,
    MemoryHit,
    MemoryQuery,
    NumericClaim,
    ResearchArtifact,
    ResearchCase,
    canonical_sha256,
)
from aegis.data import MarketSnapshot
from aegis.evidence import audit_evidence, build_claim_graph
from aegis.fund.models import ForecastIntegrityError, ResearchDossier, build_dossier
from aegis.harness.agent_loader import AgentPrompt
from aegis.harness.budgets import Budget
from aegis.harness.capability_broker import CapabilityBroker
from aegis.harness.context_compiler import compile_context
from aegis.harness.model_router import ModelProvider, ModelProviderError, ReplayModelProvider
from aegis.harness.network_guard import deny_network_io
from aegis.harness.skill_loader import SkillDefinition
from aegis.harness.state import DeskState
from aegis.memory.local_backend import LocalMemoryBackend
from aegis.memory.protocol import MemoryReader
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
        agent_prompts: dict[str, AgentPrompt],
        evidence: EvidenceBundle,
        memory_reader: MemoryReader | None = None,
    ) -> None:
        if type(model_provider) is not ReplayModelProvider:
            raise ValueError("replay graph requires the sealed ReplayModelProvider")
        if model_provider.network_enabled:
            raise ValueError("replay LangGraph provider requires a network-denied model provider")
        missing = sorted(set(_ROLE_SKILLS.values()).difference(skills))
        if missing:
            raise ValueError(f"missing graph skills: {missing}")
        self.model_provider = model_provider
        self.skills = skills
        missing_prompts = sorted(set(_ROLE_SKILLS).difference(agent_prompts))
        if missing_prompts:
            raise ValueError(f"missing graph agent prompts: {missing_prompts}")
        self.agent_prompts = agent_prompts
        self.evidence = evidence
        if memory_reader is not None and type(memory_reader) is not LocalMemoryBackend:
            raise ValueError("replay graph requires the sealed LocalMemoryBackend")
        self.memory_reader = memory_reader
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
            memory_hits=state.get("memory_hits", ()),
            memory_snapshot_hash=state.get("memory_snapshot_hash", canonical_sha256([])),
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
            prompt_versions=[self.agent_prompts[role].version_id],
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

    def _synthetic_abstention_artifact(
        self,
        state: DeskState,
        role: str,
        artifact_type: str,
        task: str,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> tuple[ResearchArtifact, GraphEvent]:
        skill = self.skills[_ROLE_SKILLS[role]]
        input_hash = self._context_hash(state, role, task)
        payload: dict[str, Any] = {
            "input_hash": input_hash,
            "output": {"abstained": True, "abstain_reason": reason, "evidence_ids": []},
        }
        if extra:
            payload.update(extra)
        artifact = ResearchArtifact(
            artifact_id=f"{state['case'].case_id}:{role}",
            case_id=state["case"].case_id,
            artifact_type=artifact_type,
            producer_agent=role,
            model_alias=skill.metadata.model_alias,
            actual_model="deterministic/auditor-failure-abstention",
            skill_versions=[skill.version_id],
            prompt_versions=[self.agent_prompts[role].version_id],
            evidence_ids=[],
            payload=payload,
            warnings=[reason],
            content_hash=canonical_sha256(payload),
        )
        event = GraphEvent(
            event_id=f"{state['case'].case_id}:{role}:complete",
            case_id=state["case"].case_id,
            sequence=_SEQUENCE[role],
            node=role,
            event_type="node_complete",
            status="abstained",
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

    @staticmethod
    def _build_claims(
        case: ResearchCase,
        evidence: EvidenceBundle,
        artifacts: tuple[ResearchArtifact, ...],
        forecasts: tuple[AlphaForecast, ...] = (),
    ) -> tuple[ClaimGraphSnapshot, tuple[ResearchArtifact, ...]]:
        claims: list[Claim] = []
        numeric_claims: list[NumericClaim] = []
        edges: list[ClaimEdge] = []
        updated_artifacts: list[ResearchArtifact] = []
        for artifact in artifacts:
            output = artifact.payload.get("output")
            summary = output.get("summary") if isinstance(output, dict) else None
            claim_ids: list[str] = []
            if isinstance(summary, str) and summary.strip() and artifact.evidence_ids:
                claim_id = f"{artifact.artifact_id}:claim"
                claim_ids.append(claim_id)
                claims.append(
                    Claim(
                        claim_id=claim_id,
                        case_id=case.case_id,
                        statement=summary,
                        claim_type=(
                            "opinion"
                            if artifact.producer_agent in {"bull", "bear", "base-rate"}
                            else "factual"
                        ),
                        material=True,
                        evidence_ids=artifact.evidence_ids,
                        status="verified",
                    )
                )
                for evidence_id in artifact.evidence_ids:
                    edges.append(
                        ClaimEdge(
                            edge_id=f"{evidence_id}:supports:{claim_id}",
                            source_kind="evidence",
                            source_id=evidence_id,
                            relation="SUPPORTS",
                            target_kind="claim",
                            target_id=claim_id,
                        )
                    )
                edges.append(
                    ClaimEdge(
                        edge_id=f"{claim_id}:used-in:{artifact.artifact_id}",
                        source_kind="claim",
                        source_id=claim_id,
                        relation="USED_IN",
                        target_kind="artifact",
                        target_id=artifact.artifact_id,
                    )
                )
            updated_artifacts.append(artifact.model_copy(update={"claim_ids": claim_ids}))
        cio_ids = [
            artifact.artifact_id for artifact in artifacts if artifact.producer_agent == "cio"
        ]
        for forecast in forecasts:
            if forecast.abstained:
                continue
            claim_id = f"{forecast.forecast_id}:claim"
            claims.append(
                Claim(
                    claim_id=claim_id,
                    case_id=case.case_id,
                    statement=forecast.thesis,
                    claim_type="forecast",
                    material=True,
                    evidence_ids=forecast.evidence_ids,
                    status="verified",
                )
            )
            for evidence_id in forecast.evidence_ids:
                edges.append(
                    ClaimEdge(
                        edge_id=f"{evidence_id}:supports:{claim_id}",
                        source_kind="evidence",
                        source_id=evidence_id,
                        relation="SUPPORTS",
                        target_kind="claim",
                        target_id=claim_id,
                    )
                )
            numeric_values = {
                "expected_excess_return": forecast.expected_excess_return,
                "expected_volatility": forecast.expected_volatility,
                "probability_positive": forecast.probability_positive,
                "confidence": forecast.confidence,
                "uncertainty": forecast.uncertainty,
                "downside_case": forecast.downside_case,
                "base_case": forecast.base_case,
                "upside_case": forecast.upside_case,
                **{f"component_{key}": value for key, value in forecast.components.items()},
            }
            for field_name, value in numeric_values.items():
                if value is None:
                    continue
                numeric_id = f"{forecast.forecast_id}:numeric:{field_name}"
                claims.append(
                    Claim(
                        claim_id=numeric_id,
                        case_id=case.case_id,
                        statement=f"{forecast.ticker} {field_name} is {value}",
                        claim_type="numeric",
                        material=True,
                        evidence_ids=forecast.evidence_ids,
                        status="verified",
                    )
                )
                numeric_claims.append(
                    NumericClaim(
                        claim_id=numeric_id,
                        name=field_name,
                        value=Decimal(str(value)),
                        unit="ratio",
                        evidence_id=forecast.evidence_ids[0],
                        coordinates=(f"forecast_id={forecast.forecast_id};field={field_name}"),
                        calculation_id=f"{forecast.model_name}:structured-output-v1",
                    )
                )
                for evidence_id in forecast.evidence_ids:
                    edges.append(
                        ClaimEdge(
                            edge_id=f"{evidence_id}:supports:{numeric_id}",
                            source_kind="evidence",
                            source_id=evidence_id,
                            relation="SUPPORTS",
                            target_kind="claim",
                            target_id=numeric_id,
                        )
                    )
            if cio_ids:
                edges.append(
                    ClaimEdge(
                        edge_id=f"{cio_ids[0]}:used-in:{forecast.forecast_id}",
                        source_kind="artifact",
                        source_id=cio_ids[0],
                        relation="USED_IN",
                        target_kind="forecast",
                        target_id=forecast.forecast_id,
                    )
                )
        return build_claim_graph(case.case_id, claims, numeric_claims, edges), tuple(
            updated_artifacts
        )

    def _audit(self, state: DeskState) -> DeskState:
        specialist_ids = [
            f"{state['case'].case_id}:{role}"
            for role in ("quant", "fundamentals", "event-behavioral")
        ]
        specialist_artifacts = tuple(state["artifacts"][key] for key in specialist_ids)
        claim_graph, _ = self._build_claims(state["case"], state["evidence"], specialist_artifacts)
        deterministic_audit = audit_evidence(state["evidence"], claim_graph, EvidenceAuditPolicy())
        if not deterministic_audit.approved:
            raise ForecastIntegrityError("deterministic evidence audit blocked the case")
        audited_hash = canonical_sha256(
            {
                "artifacts": [artifact.content_hash for artifact in specialist_artifacts],
                "evidence": state["evidence"],
                "claim_graph": claim_graph,
                "deterministic_audit": deterministic_audit,
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
        update["claim_graph"] = claim_graph
        update["deterministic_audit"] = deterministic_audit
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
                artifact, event = self._synthetic_abstention_artifact(
                    state,
                    role,
                    f"{role}_opening_memo",
                    f"Produce the independent {role} opening memo.",
                    "evidence auditor failed; no evidence was approved",
                    {"opening_input_hash": opening_input_hash},
                )
            else:
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
        failed_roles = set(state.get("failed_roles", frozenset()))
        if "evidence-auditor" in failed_roles:
            artifact, event = self._synthetic_abstention_artifact(
                state,
                "cio",
                "cio_synthesis",
                "Synthesize only approved artifacts into AlphaForecasts.",
                "evidence auditor failed; no evidence was approved",
                {"synthesis_input_hash": synthesis_hash},
            )
        else:
            artifact, event = self._artifact(
                state,
                "cio",
                "cio_synthesis",
                "Synthesize only approved artifacts into AlphaForecasts.",
                {"synthesis_input_hash": synthesis_hash},
                approved_ids,
            )
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
        auditor_failed = "evidence-auditor" in state.get("failed_roles", frozenset())
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
        if auditor_failed:
            artifact, event = self._synthetic_abstention_artifact(
                state,
                "verifier",
                "forecast_verification",
                "Verify forecast schema, evidence coverage, horizon, and numeric coherence.",
                "evidence auditor failed; verification cannot authorize evidence",
                {"deterministic_checks_passed": valid},
            )
        else:
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
        memory_hits: tuple[MemoryHit, ...] = ()
        memory_snapshot_hash = canonical_sha256([])
        if self.memory_reader is not None:
            memory_hits = self.memory_reader.search(
                MemoryQuery(
                    text=case.research_question,
                    as_of=case.as_of,
                    entity_ids=list(case.tickers),
                    top_k=8,
                )
            )
            if any(
                hit.item.status != "approved"
                or hit.item.available_at > case.as_of
                or (hit.item.expires_at is not None and hit.item.expires_at <= case.as_of)
                for hit in memory_hits
            ):
                raise ForecastIntegrityError("memory backend returned ineligible memory")
            memory_snapshot_hash = self.memory_reader.snapshot(case.as_of).content_hash
        initial: DeskState = {
            "case": case,
            "snapshot": snapshot,
            "evidence": self.evidence,
            "artifacts": {},
            "events": {},
            "failed_roles": frozenset(),
            "approved_evidence_ids": (),
            "memory_hits": memory_hits,
            "memory_snapshot_hash": memory_snapshot_hash,
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
        claim_graph, artifacts = self._build_claims(case, self.evidence, artifacts, forecasts)
        deterministic_audit = audit_evidence(self.evidence, claim_graph, EvidenceAuditPolicy())
        if not deterministic_audit.approved:
            raise ForecastIntegrityError("final deterministic evidence audit blocked the case")
        return build_dossier(
            case,
            self.evidence,
            artifacts,
            forecasts,
            events,
            claim_graph,
            deterministic_audit,
            memory_hits,
            memory_snapshot_hash,
        )
