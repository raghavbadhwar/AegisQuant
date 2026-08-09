"""Isolated, calculation-first, evidence-confined fundamental research graph."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from operator import add
from pathlib import Path
from typing import Annotated, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from aegis.contracts import (
    REQUIRED_SPECIALIST_ROLES,
    CalculationLineage,
    CompanyResearchRequest,
    FundamentalCommitteeDecision,
    FundamentalResearchDossier,
    FundamentalSpecialistArtifact,
    FundamentalSpecialistClaim,
    FundamentalSpecialistInput,
    RawFilingSnapshot,
    SpecialistCalculationPredicate,
)
from aegis.contracts.fundamentals import SpecialistRole
from aegis.harness.agent_loader import AgentPrompt, load_agent_prompt
from aegis.harness.skill_loader import SkillDefinition, load_skill

from .archetypes import route_archetype
from .fixtures import load_fundamental_fixture
from .hashing import build_hashed
from .service import (
    FundamentalResearchInputs,
    _abstained_dossier,
    _abstained_forecast,
    _compute_preliminary_research,
    _finalize_verified_research,
)


class FundamentalGraphError(RuntimeError):
    pass


@dataclass(frozen=True)
class FundamentalGraphBundle:
    request: CompanyResearchRequest
    snapshot: RawFilingSnapshot
    inputs: FundamentalResearchInputs


class FundamentalResearchProvider(Protocol):
    def load(self, request: CompanyResearchRequest) -> FundamentalGraphBundle: ...

    def analyze_role(
        self,
        request: CompanyResearchRequest,
        role_input: FundamentalSpecialistInput,
    ) -> FundamentalSpecialistArtifact: ...


@dataclass(frozen=True)
class _RoleSemanticRule:
    output_name: str
    supportive_at_or_above: Decimal
    cautionary_at_or_below: Decimal


_ROLE_SEMANTICS: dict[SpecialistRole, _RoleSemanticRule] = {
    "business_industry": _RoleSemanticRule("revenue_cagr", Decimal("0.05"), Decimal("0")),
    "financial_quality": _RoleSemanticRule("cash_conversion", Decimal("0.80"), Decimal("0.50")),
    "growth_drivers": _RoleSemanticRule("growth", Decimal("0.15"), Decimal("0")),
    "accounting_quality": _RoleSemanticRule("accounting", Decimal("0.75"), Decimal("0")),
    "balance_sheet": _RoleSemanticRule("balance_sheet", Decimal("0.50"), Decimal("0")),
    "capital_allocation": _RoleSemanticRule(
        "capital_allocation", Decimal("0.05"), Decimal("-0.05")
    ),
    "management_guidance": _RoleSemanticRule("management", Decimal("0.25"), Decimal("-0.25")),
    "valuation": _RoleSemanticRule("valuation", Decimal("0.10"), Decimal("0")),
    "catalysts_risks": _RoleSemanticRule("catalyst", Decimal("0.05"), Decimal("-0.05")),
}


def _semantic_interpretation(
    role: SpecialistRole,
    calculations: tuple[CalculationLineage, ...] | list[CalculationLineage],
) -> tuple[
    CalculationLineage,
    Literal["supportive", "neutral", "cautionary"],
    list[SpecialistCalculationPredicate],
]:
    rule = _ROLE_SEMANTICS[role]
    matching = sorted(
        (item for item in calculations if item.output_name == rule.output_name),
        key=lambda item: item.calculation_id,
    )
    if len(matching) != 1:
        raise FundamentalGraphError(
            f"specialist semantic input is not unique for {role}: {rule.output_name}"
        )
    calculation = matching[0]
    value = Decimal(str(calculation.output_value))
    if value >= rule.supportive_at_or_above:
        conclusion: Literal["supportive", "neutral", "cautionary"] = "supportive"
        predicates = [
            SpecialistCalculationPredicate(
                calculation_id=calculation.calculation_id,
                operator="ge",
                reference_value=rule.supportive_at_or_above,
            )
        ]
    elif value <= rule.cautionary_at_or_below:
        conclusion = "cautionary"
        predicates = [
            SpecialistCalculationPredicate(
                calculation_id=calculation.calculation_id,
                operator="le",
                reference_value=rule.cautionary_at_or_below,
            )
        ]
    else:
        conclusion = "neutral"
        predicates = [
            SpecialistCalculationPredicate(
                calculation_id=calculation.calculation_id,
                operator="gt",
                reference_value=rule.cautionary_at_or_below,
            ),
            SpecialistCalculationPredicate(
                calculation_id=calculation.calculation_id,
                operator="lt",
                reference_value=rule.supportive_at_or_above,
            ),
        ]
    return calculation, conclusion, predicates


def _canonical_statement(
    role: SpecialistRole,
    conclusion: str,
    calculation: CalculationLineage,
    predicates: list[SpecialistCalculationPredicate],
) -> str:
    constraints = " and ".join(
        f"{predicate.operator} {predicate.reference_value}" for predicate in predicates
    )
    return (
        f"{role} assessment is {conclusion}: verified "
        f"{calculation.output_name}={calculation.output_value} from "
        f"{calculation.calculation_id} satisfies {constraints}."
    )


class FixtureFundamentalProvider:
    """Sealed replay provider whose specialists run only after calculations exist."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        root = Path(__file__).resolve().parents[2]
        self._agent_prompts: dict[SpecialistRole, AgentPrompt] = {}
        self._skills: dict[SpecialistRole, SkillDefinition] = {}
        for role in REQUIRED_SPECIALIST_ROLES:
            self._agent_prompts[role] = load_agent_prompt(
                root / "aegis" / "agents" / f"fundamental_{role}" / "AGENT.md",
                root=root / "aegis" / "agents",
            )
            self._skills[role] = load_skill(
                root / "skills" / f"fundamental-{role.replace('_', '-')}" / "SKILL.md",
                root=root / "skills",
            )

    def load(self, request: CompanyResearchRequest) -> FundamentalGraphBundle:
        fixture_request, snapshot, inputs = load_fundamental_fixture(self.path)
        if fixture_request != request:
            raise FundamentalGraphError("provider fixture does not match the research request")
        return FundamentalGraphBundle(request, snapshot, inputs)

    def analyze_role(
        self,
        request: CompanyResearchRequest,
        role_input: FundamentalSpecialistInput,
    ) -> FundamentalSpecialistArtifact:
        if role_input.request_id != request.request_id or role_input.as_of != request.as_of:
            raise FundamentalGraphError("specialist input is not request bound")
        role = role_input.role
        calculation, conclusion, predicates = _semantic_interpretation(
            role, role_input.calculation_lineage
        )
        claim = FundamentalSpecialistClaim(
            claim_id=f"{request.request_id}:{role}:claim",
            statement=_canonical_statement(role, conclusion, calculation, predicates),
            conclusion=conclusion,
            confidence=0.75,
            evidence_ids=role_input.evidence_ids,
            calculation_ids=[calculation.calculation_id],
            predicates=predicates,
        )
        prompt = self._agent_prompts[role]
        skill = self._skills[role]
        values = {
            "artifact_id": f"{request.request_id}:{role}",
            "request_id": request.request_id,
            "role": role,
            "as_of": request.as_of,
            "producer": f"{prompt.version_id}|{skill.version_id}",
            "claims": [claim],
            "abstained": False,
            "abstain_reason": None,
            "contract_version": "3.0.0",
        }
        return build_hashed(FundamentalSpecialistArtifact, **values)


class _SpecialistGraphState(TypedDict):
    request: CompanyResearchRequest
    role_inputs: dict[SpecialistRole, FundamentalSpecialistInput]
    artifacts: Annotated[list[FundamentalSpecialistArtifact], add]


def _run_parallel_specialists(
    provider: FundamentalResearchProvider,
    request: CompanyResearchRequest,
    role_inputs: tuple[FundamentalSpecialistInput, ...],
) -> tuple[FundamentalSpecialistArtifact, ...]:
    by_role = {item.role: item for item in role_inputs}
    builder = StateGraph(_SpecialistGraphState)
    node_names = []
    for role in REQUIRED_SPECIALIST_ROLES:
        node_name = f"specialist_{role}"
        node_names.append(node_name)

        def run_role(
            state: _SpecialistGraphState,
            selected_role: SpecialistRole = role,
        ) -> dict[str, list[FundamentalSpecialistArtifact]]:
            return {
                "artifacts": [
                    provider.analyze_role(state["request"], state["role_inputs"][selected_role])
                ]
            }

        builder.add_node(node_name, run_role)
        builder.add_edge(START, node_name)
    builder.add_node("join", lambda _state: {})
    builder.add_edge(node_names, "join")
    builder.add_edge("join", END)
    result = builder.compile().invoke({"request": request, "role_inputs": by_role, "artifacts": []})
    return tuple(result["artifacts"])


def _audit_bundle(bundle: FundamentalGraphBundle) -> FundamentalResearchInputs:
    request = bundle.request
    snapshot = bundle.snapshot
    if snapshot.ticker != request.ticker or snapshot.as_of != request.as_of:
        raise FundamentalGraphError("point-in-time snapshot does not align with request")
    if any(fact.available_at > request.as_of for fact in snapshot.facts):
        raise FundamentalGraphError("future filing fact reached the specialist graph")
    if (
        bundle.inputs.available_at > request.as_of
        or bundle.inputs.evidence.as_of != request.as_of
        or any(record.available_at > request.as_of for record in bundle.inputs.evidence.records)
    ):
        raise FundamentalGraphError("future non-filing evidence reached the specialist graph")
    return bundle.inputs


def _role_calculation_ids(
    dossier: FundamentalResearchDossier,
) -> dict[SpecialistRole, list[str]]:
    assert dossier.metrics is not None
    assert dossier.management is not None
    assert dossier.comparables is not None
    assert dossier.scenario_valuation is not None
    metric_ids = dossier.metrics.calculation_ids
    forecast_ids = [
        calculation_id
        for forecast in dossier.forecasts.values()
        for calculation_id in forecast.calculation_ids
    ]
    valuation_ids = [
        *[
            calculation_id
            for result in dossier.dcf.values()
            for calculation_id in result.calculation_ids
        ],
        *dossier.comparables.calculation_ids,
        *dossier.scenario_valuation.calculation_ids,
        *[
            calculation_id
            for result in dossier.reverse_dcf.values()
            for calculation_id in result.calculation_ids
        ],
    ]
    scorecard_ids = dossier.scorecard.calculation_ids if dossier.scorecard else []
    return {
        "business_industry": metric_ids,
        "financial_quality": metric_ids,
        "growth_drivers": [*metric_ids, *forecast_ids, *scorecard_ids],
        "accounting_quality": [
            *(dossier.accounting.calculation_ids if dossier.accounting else metric_ids),
            *scorecard_ids,
        ],
        "balance_sheet": [*metric_ids, *scorecard_ids],
        "capital_allocation": [*metric_ids, *scorecard_ids],
        "management_guidance": [*dossier.management.calculation_ids, *scorecard_ids],
        "valuation": [*valuation_ids, *scorecard_ids],
        "catalysts_risks": [*dossier.scenario_valuation.calculation_ids, *scorecard_ids],
    }


def _build_role_inputs(
    request: CompanyResearchRequest,
    inputs: FundamentalResearchInputs,
    dossier: FundamentalResearchDossier,
) -> tuple[FundamentalSpecialistInput, ...]:
    lineage_by_id = {item.calculation_id: item for item in dossier.calculation_lineage}
    result = []
    for role, calculation_ids in _role_calculation_ids(dossier).items():
        unique_ids = sorted(set(calculation_ids))
        if not unique_ids or not set(unique_ids).issubset(lineage_by_id):
            raise FundamentalGraphError(
                f"specialist lacks closed verified calculation context: {role}"
            )
        values = {
            "specialist_input_id": f"{request.request_id}:{role}:input",
            "request_id": request.request_id,
            "role": role,
            "as_of": request.as_of,
            "evidence_ids": sorted(inputs.evidence_ids),
            "calculation_lineage": [lineage_by_id[item] for item in unique_ids],
            "contract_version": "3.0.0",
        }
        result.append(build_hashed(FundamentalSpecialistInput, **values))
    return tuple(result)


def _predicate_holds(
    predicate: SpecialistCalculationPredicate,
    calculation: CalculationLineage,
) -> bool:
    value = Decimal(str(calculation.output_value))
    reference = predicate.reference_value
    tolerance = predicate.tolerance
    if predicate.operator == "gt":
        return value > reference + tolerance
    if predicate.operator == "ge":
        return value >= reference - tolerance
    if predicate.operator == "lt":
        return value < reference - tolerance
    if predicate.operator == "le":
        return value <= reference + tolerance
    return abs(value - reference) <= tolerance


def _audit_specialists(
    request: CompanyResearchRequest,
    role_inputs: tuple[FundamentalSpecialistInput, ...],
    artifacts: tuple[FundamentalSpecialistArtifact, ...],
) -> tuple[FundamentalSpecialistArtifact, ...]:
    inputs_by_role = {item.role: item for item in role_inputs}
    artifacts_by_role = {item.role: item for item in artifacts}
    if (
        set(inputs_by_role) != set(REQUIRED_SPECIALIST_ROLES)
        or set(artifacts_by_role) != set(REQUIRED_SPECIALIST_ROLES)
        or len(artifacts_by_role) != len(artifacts)
    ):
        raise FundamentalGraphError("exactly one artifact from every specialist is required")
    for role in REQUIRED_SPECIALIST_ROLES:
        role_input = inputs_by_role[role]
        artifact = artifacts_by_role[role]
        if artifact.request_id != request.request_id or artifact.as_of != request.as_of:
            raise FundamentalGraphError("specialist artifact is not bound to the request")
        if artifact.abstained:
            continue
        allowed_evidence = set(role_input.evidence_ids)
        calculations = {item.calculation_id: item for item in role_input.calculation_lineage}
        for claim in artifact.claims:
            if not set(claim.evidence_ids).issubset(allowed_evidence):
                raise FundamentalGraphError("specialist attempted evidence widening")
            if not set(claim.calculation_ids).issubset(calculations):
                raise FundamentalGraphError("specialist cited an unavailable calculation")
            expected_calculation, expected_conclusion, expected_predicates = (
                _semantic_interpretation(role, list(calculations.values()))
            )
            if (
                claim.conclusion != expected_conclusion
                or claim.calculation_ids != [expected_calculation.calculation_id]
                or claim.predicates != expected_predicates
                or claim.statement
                != _canonical_statement(
                    role,
                    expected_conclusion,
                    expected_calculation,
                    expected_predicates,
                )
                or any(
                    not _predicate_holds(predicate, expected_calculation)
                    for predicate in expected_predicates
                )
            ):
                raise FundamentalGraphError(
                    "specialist conclusion contradicts verified calculations "
                    "under role-specific semantics"
                )
    return tuple(artifacts_by_role[role] for role in REQUIRED_SPECIALIST_ROLES)


def run_fundamental_graph(
    request: CompanyResearchRequest,
    provider: FundamentalResearchProvider,
) -> FundamentalResearchDossier:
    bundle = provider.load(request)
    if bundle.request != request:
        raise FundamentalGraphError("provider changed the research request")
    audited_inputs = _audit_bundle(bundle)
    preliminary = _compute_preliminary_research(request, bundle.snapshot, audited_inputs)
    if preliminary.abstained:
        values = {
            name: getattr(preliminary, name)
            for name in type(preliminary).model_fields
            if name != "content_hash"
        }
        values["release_status"] = "terminal_abstention"
        values["alpha_forecast"] = _abstained_forecast(
            request,
            preliminary.abstain_reason or "unsupported archetype",
            verification_status="terminal_abstention",
        )
        return build_hashed(FundamentalResearchDossier, **values)
    role_inputs = _build_role_inputs(request, audited_inputs, preliminary)
    artifacts = _audit_specialists(
        request, role_inputs, _run_parallel_specialists(provider, request, role_inputs)
    )
    abstainers = [artifact for artifact in artifacts if artifact.abstained]
    if abstainers:
        archetype = route_archetype(
            request.ticker,
            sector=audited_inputs.sector,
            subscription_revenue_share=audited_inputs.subscription_revenue_share,
            profitable=audited_inputs.profitable,
        )
        reason = "required specialists abstained: " + ", ".join(
            sorted(artifact.role for artifact in abstainers)
        )
        abstained = _abstained_dossier(
            request,
            bundle.snapshot,
            reason,
            archetype,
            audited_inputs.content_hash,
            artifacts,
        )
        committee = build_hashed(
            FundamentalCommitteeDecision,
            committee_id=f"fundamental-committee-{request.request_id}",
            request_id=request.request_id,
            specialist_artifact_ids=sorted(artifact.artifact_id for artifact in artifacts),
            accepted_claim_ids=[],
            evidence_ids=[],
            calculation_ids=[],
            decision="abstained",
            rationale="One or more required post-calculation specialists abstained.",
            contract_version="3.0.0",
        )
        values = {
            name: getattr(abstained, name)
            for name in type(abstained).model_fields
            if name != "content_hash"
        }
        values.update(
            {
                "alpha_forecast": _abstained_forecast(
                    request,
                    reason,
                    verification_status="committee_verified",
                    committee_id=committee.committee_id,
                    committee_content_hash=committee.content_hash,
                ),
                "committee_decision": committee,
                "release_status": "committee_verified",
            }
        )
        return build_hashed(FundamentalResearchDossier, **values)
    claim_ids = [claim.claim_id for artifact in artifacts for claim in artifact.claims]
    cited_calculations = {
        calculation_id
        for artifact in artifacts
        for claim in artifact.claims
        for calculation_id in claim.calculation_ids
    }
    if not cited_calculations.issubset(set(preliminary.calculation_ids)):
        raise FundamentalGraphError("specialist cited an unaudited calculation")
    committee_values = {
        "committee_id": f"fundamental-committee-{request.request_id}",
        "request_id": request.request_id,
        "specialist_artifact_ids": sorted(artifact.artifact_id for artifact in artifacts),
        "accepted_claim_ids": sorted(claim_ids),
        "evidence_ids": preliminary.evidence_ids,
        "calculation_ids": preliminary.calculation_ids,
        "decision": "approved",
        "rationale": (
            "Every accepted role conclusion was produced from its post-calculation "
            "typed input and passed evidence, calculation, predicate and canonical-claim checks."
        ),
        "contract_version": "3.0.0",
    }
    committee = build_hashed(FundamentalCommitteeDecision, **committee_values)
    verified = _finalize_verified_research(
        preliminary,
        audited_inputs,
        artifacts,
        committee,
    )
    if verified.alpha_forecast.abstained:
        raise FundamentalGraphError("forecast verifier rejected a complete dossier")
    if not verified.calculation_ids or not verified.evidence_ids:
        raise FundamentalGraphError("dossier failed evidence/calculation verification")
    return verified
