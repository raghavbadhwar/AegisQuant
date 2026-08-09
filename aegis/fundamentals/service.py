"""Deterministic company-research service independent of fund execution."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from pydantic import AwareDatetime, Field, model_validator

from aegis.contracts import (
    AccountingQualityAssessment,
    AlphaForecast,
    BusinessModelAssessment,
    CalculationLineage,
    CompanyArchetype,
    CompanyResearchRequest,
    DCFResult,
    EvidenceBundle,
    ForecastCalibrationRecord,
    ForecastDriver,
    FundamentalResearchDossier,
    FundamentalScorecard,
    FundamentalSpecialistArtifact,
    GuidanceRecord,
    IndustryAssessment,
    InvestmentThesis,
    ManagementActionRecord,
    PeerMultiple,
    RawFilingSnapshot,
    ScenarioValuation,
    SOTPResult,
    ThesisCheckpoint,
    ThesisClaim,
    canonical_sha256,
)
from aegis.contracts._base import ContractModel

from .archetypes import route_archetype
from .forecasting import forecast_operating_case, validate_scenario_ordering
from .hashing import build_hashed
from .management import evaluate_management
from .metrics import calculate_metrics
from .normalization import normalize_statements
from .thesis import build_thesis
from .valuation import (
    calculate_comparables,
    calculate_dcf,
    combine_scenarios,
    solve_implied_assumption,
    solve_implied_growth,
)


class FundamentalResearchError(RuntimeError):
    pass


class FundamentalResearchInputs(ContractModel):
    input_snapshot_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    available_at: AwareDatetime
    source_receipt_ids: list[str] = Field(min_length=1)
    evidence: EvidenceBundle
    field_evidence: dict[str, list[str]] = Field(min_length=1)
    sector: str
    industry: str
    market_price: Decimal = Field(gt=0, allow_inf_nan=False)
    discount_rate: float = Field(gt=0, lt=1, allow_inf_nan=False)
    terminal_growth_by_scenario: dict[str, float]
    terminal_roic_by_scenario: dict[str, float]
    scenario_probabilities: dict[str, float]
    drivers: tuple[ForecastDriver, ...] = Field(min_length=1)
    peers: tuple[PeerMultiple, ...] = Field(min_length=2)
    guidance: tuple[GuidanceRecord, ...] = ()
    management_actions: tuple[ManagementActionRecord, ...] = ()
    revenue_driver_descriptions: tuple[str, ...] = Field(min_length=1)
    competitors: tuple[str, ...] = ()
    catalysts: tuple[str, ...] = ()
    risks: tuple[str, ...] = Field(min_length=1)
    subscription_revenue_share: float = Field(ge=0, le=1)
    profitable: bool
    expected_volatility: float = Field(gt=0, allow_inf_nan=False)
    calibration: ForecastCalibrationRecord
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_version: str = "3.0.0"

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(record.evidence_id for record in self.evidence.records)

    @model_validator(mode="after")
    def provenance_is_complete_and_hashed(self) -> FundamentalResearchInputs:
        required_fields = {
            "market_price",
            "discount_rate",
            "terminal_assumptions",
            "scenario_probabilities",
            "drivers",
            "peers",
            "guidance",
            "management_actions",
            "business_industry",
            "catalysts_risks",
            "expected_volatility",
            "calibration",
        }
        if set(self.field_evidence) != required_fields:
            raise ValueError("fundamental input field-evidence map is incomplete")
        evidence_ids = set(self.evidence_ids)
        if not any(self.ticker in record.entity_ids for record in self.evidence.records):
            raise ValueError("fundamental input evidence does not resolve the ticker")
        if any(record.injection_flags for record in self.evidence.records):
            raise ValueError("fundamental input evidence contains injection flags")
        if any(record.extraction_confidence < 0.8 for record in self.evidence.records):
            raise ValueError("fundamental input evidence confidence is below policy")
        if any(
            not ids or not set(ids).issubset(evidence_ids) for ids in self.field_evidence.values()
        ):
            raise ValueError("fundamental input field evidence is unresolved")
        evidence_by_id = {record.evidence_id: record for record in self.evidence.records}
        issuer_fields = {
            "market_price",
            "drivers",
            "guidance",
            "management_actions",
            "business_industry",
            "catalysts_risks",
            "expected_volatility",
        }
        for field_name in issuer_fields:
            if any(
                self.ticker not in evidence_by_id[evidence_id].entity_ids
                for evidence_id in self.field_evidence[field_name]
            ):
                raise ValueError(
                    f"fundamental input field evidence does not resolve issuer: {field_name}"
                )
        peer_entities = {peer.ticker for peer in self.peers}
        resolved_peer_entities = {
            entity_id
            for evidence_id in self.field_evidence["peers"]
            for entity_id in evidence_by_id[evidence_id].entity_ids
        }
        if not peer_entities.issubset(resolved_peer_entities):
            raise ValueError("peer field evidence does not resolve every peer entity")
        embedded_groups = (
            ("drivers", self.drivers),
            ("guidance", self.guidance),
            ("management_actions", self.management_actions),
        )
        for field_name, items in embedded_groups:
            allowed = set(self.field_evidence[field_name])
            for item in items:
                if not set(item.evidence_ids).issubset(allowed):
                    raise ValueError(
                        f"embedded {field_name} evidence is outside its field provenance"
                    )
        allowed_peer_evidence = set(self.field_evidence["peers"])
        for peer in self.peers:
            if not set(peer.evidence_ids).issubset(allowed_peer_evidence):
                raise ValueError("embedded peer evidence is outside field provenance")
            if not any(
                peer.ticker in evidence_by_id[evidence_id].entity_ids
                for evidence_id in peer.evidence_ids
            ):
                raise ValueError("embedded peer evidence does not resolve peer entity")
        if self.available_at > self.evidence.as_of:
            raise ValueError("input snapshot availability follows its evidence cutoff")
        if self.calibration.available_at > self.available_at:
            raise ValueError("forecast calibration is not point-in-time eligible")
        if any(
            (
                action.completion_available_at is not None
                and action.completion_available_at > self.available_at
            )
            or (
                action.outcome_available_at is not None
                and action.outcome_available_at > self.available_at
            )
            for action in self.management_actions
        ):
            raise ValueError("management action state is not point-in-time eligible")
        if self.calibration.model_name != "fundamental-alpha-v1":
            raise ValueError("forecast calibration model does not match")
        expected = canonical_sha256(self.model_dump(exclude={"content_hash"}))
        if self.content_hash != expected:
            raise ValueError("fundamental input snapshot hash mismatch")
        return self


def _derived_lineage(
    calculation_id: str,
    calculator: str,
    formula: str,
    output_name: str,
    output_value: Decimal | float,
    *,
    input_calculation_ids: list[str],
    input_assumption_ids: list[str] | None = None,
    unit: str = "ratio",
) -> CalculationLineage:
    values = {
        "calculation_id": calculation_id,
        "calculator": calculator,
        "calculator_version": "1.0.0",
        "formula": formula,
        "input_fact_ids": [],
        "input_calculation_ids": input_calculation_ids,
        "input_assumption_ids": input_assumption_ids or [],
        "output_name": output_name,
        "output_value": output_value,
        "unit": unit,
        "contract_version": "3.0.0",
    }
    return build_hashed(CalculationLineage, **values)


def _clamp(value: float) -> float:
    return min(1.0, max(-1.0, value))


def _abstained_forecast(request: CompanyResearchRequest, reason: str) -> AlphaForecast:
    return AlphaForecast(
        forecast_id=f"fundamental-{request.request_id}-abstain",
        model_name="fundamental-alpha-v1",
        ticker=request.ticker,
        as_of=request.as_of,
        horizon_days=request.horizon_days,
        expected_excess_return=None,
        expected_volatility=None,
        probability_positive=0.0,
        confidence=0.0,
        uncertainty=1.0,
        thesis="",
        evidence_ids=[],
        invalidation_conditions=[],
        thesis_expiry=None,
        abstained=True,
        abstain_reason=reason,
        components={},
        metadata={"provider": "fundamental-research-v3"},
    )


def _abstained_dossier(
    request: CompanyResearchRequest,
    snapshot: RawFilingSnapshot,
    reason: str,
    archetype: CompanyArchetype,
    input_snapshot_hash: str,
    specialist_artifacts: tuple[FundamentalSpecialistArtifact, ...] = (),
) -> FundamentalResearchDossier:
    values = {
        "dossier_id": f"fundamental-dossier-{request.request_id}",
        "request": request,
        "archetype": archetype,
        "source_snapshot_hash": snapshot.content_hash,
        "input_snapshot_hash": input_snapshot_hash,
        "input_evidence": None,
        "statements": None,
        "metrics": None,
        "business": None,
        "industry": None,
        "accounting": None,
        "management": None,
        "forecasts": {},
        "dcf": {},
        "reverse_dcf": {},
        "comparables": None,
        "sotp": None,
        "scenario_valuation": None,
        "scorecard": None,
        "thesis": None,
        "alpha_forecast": _abstained_forecast(request, reason),
        "specialist_artifacts": list(specialist_artifacts),
        "specialist_findings": {
            artifact.role: [claim.statement for claim in artifact.claims]
            for artifact in specialist_artifacts
        },
        "release_status": "preliminary",
        "committee_decision": None,
        "evidence_ids": [],
        "calculation_ids": [],
        "calculation_lineage": [],
        "known_gaps": [reason],
        "abstained": True,
        "abstain_reason": reason,
        "contract_version": "3.0.0",
    }
    return build_hashed(FundamentalResearchDossier, **values)


def compute_preliminary_research(
    request: CompanyResearchRequest,
    snapshot: RawFilingSnapshot,
    inputs: FundamentalResearchInputs,
    specialist_artifacts: tuple[FundamentalSpecialistArtifact, ...] = (),
) -> FundamentalResearchDossier:
    if snapshot.ticker != request.ticker or snapshot.as_of != request.as_of:
        raise FundamentalResearchError("research request and filing snapshot do not align")
    if (
        inputs.request_id != request.request_id
        or inputs.ticker != request.ticker
        or inputs.evidence.case_id != request.request_id
    ):
        raise FundamentalResearchError("non-filing research inputs are not entity/request bound")
    expected_evidence_mode = {
        "replay": "replay",
        "historical": "historical",
        "current_research": "live_research",
    }[request.mode]
    if inputs.evidence.mode != expected_evidence_mode:
        raise FundamentalResearchError("research request and evidence modes do not match")
    if inputs.available_at > request.as_of or inputs.evidence.as_of != request.as_of:
        raise FundamentalResearchError("non-filing research inputs are not point-in-time eligible")
    if not (
        inputs.calibration.horizon_days_min
        <= request.horizon_days
        <= inputs.calibration.horizon_days_max
    ):
        raise FundamentalResearchError("forecast horizon is outside calibration support")
    specialist_by_role = {artifact.role: artifact for artifact in specialist_artifacts}
    specialist_text = {
        role: " ".join(claim.statement for claim in artifact.claims)
        for role, artifact in specialist_by_role.items()
        if not artifact.abstained
    }
    archetype = route_archetype(
        request.ticker,
        sector=inputs.sector,
        subscription_revenue_share=inputs.subscription_revenue_share,
        profitable=inputs.profitable,
    )
    if not archetype.supported:
        return _abstained_dossier(
            request,
            snapshot,
            archetype.reason,
            archetype,
            inputs.content_hash,
            specialist_artifacts,
        )
    if inputs.market_price <= 0 or not inputs.evidence_ids:
        raise FundamentalResearchError("research inputs require market price and evidence")
    statements = normalize_statements(snapshot)
    metrics, metric_lineage = calculate_metrics(statements, market_price=inputs.market_price)
    management = evaluate_management(
        statements, list(inputs.guidance), list(inputs.management_actions)
    )
    forecasts = {}
    forecast_lineage: list[CalculationLineage] = []
    for scenario in ("bear", "base", "bull"):
        case_drivers = [driver for driver in inputs.drivers if driver.scenario == scenario]
        forecast, lineage = forecast_operating_case(
            statements,
            scenario,
            case_drivers,
            terminal_growth=inputs.terminal_growth_by_scenario[scenario],
            terminal_roic=inputs.terminal_roic_by_scenario[scenario],
        )
        forecasts[scenario] = forecast
        forecast_lineage.extend(lineage)
    validate_scenario_ordering(forecasts)
    dcf: dict[str, DCFResult] = {}
    dcf_lineage: list[CalculationLineage] = []
    for scenario in ("bear", "base", "bull"):
        result, lineage = calculate_dcf(
            forecasts[scenario],
            discount_rate=inputs.discount_rate,
            terminal_growth=inputs.terminal_growth_by_scenario[scenario],
            net_debt=Decimal(str(metrics.net_debt)),
            evidence_ids=list(inputs.evidence_ids),
        )
        dcf[scenario] = result
        dcf_lineage.extend(lineage)
    scenario_valuation: ScenarioValuation = combine_scenarios(
        ticker=request.ticker,
        dcf_by_scenario=dcf,
        probabilities=inputs.scenario_probabilities,
        market_price=inputs.market_price,
    )
    base_drivers = [driver for driver in inputs.drivers if driver.scenario == "base"]

    def value_for_drivers(modified: list[ForecastDriver]) -> Decimal:
        forecast, _ = forecast_operating_case(
            statements,
            "base",
            modified,
            terminal_growth=inputs.terminal_growth_by_scenario["base"],
            terminal_roic=inputs.terminal_roic_by_scenario["base"],
        )
        result, _ = calculate_dcf(
            forecast,
            discount_rate=inputs.discount_rate,
            terminal_growth=inputs.terminal_growth_by_scenario["base"],
            net_debt=Decimal(str(metrics.net_debt)),
            evidence_ids=list(inputs.evidence_ids),
        )
        return result.value_per_share

    def value_for_growth(growth: float) -> Decimal:
        return value_for_drivers(
            [
                driver.model_copy(update={"value": growth})
                if driver.name == "revenue_growth"
                else driver
                for driver in base_drivers
            ]
        )

    def value_for_margin(margin: float) -> Decimal:
        return value_for_drivers(
            [
                driver.model_copy(update={"value": margin})
                if driver.name == "operating_margin"
                else driver
                for driver in base_drivers
            ]
        )

    growth_by_year = {
        driver.year: driver.value for driver in base_drivers if driver.name == "revenue_growth"
    }
    first_forecast_year = min(growth_by_year)

    def value_for_duration(duration: float) -> Decimal:
        modified: list[ForecastDriver] = []
        terminal_growth = inputs.terminal_growth_by_scenario["base"]
        for driver in base_drivers:
            if driver.name != "revenue_growth":
                modified.append(driver)
                continue
            year_index = driver.year - first_forecast_year
            active_fraction = min(1.0, max(0.0, duration - year_index))
            effective_growth = terminal_growth + active_fraction * (
                growth_by_year[driver.year] - terminal_growth
            )
            modified.append(driver.model_copy(update={"value": effective_growth}))
        return value_for_drivers(modified)

    assumption_ids = [item.assumption_id for item in dcf["base"].assumptions]
    reverse_dcf = {
        "revenue_growth": solve_implied_growth(
            ticker=request.ticker,
            market_price=inputs.market_price,
            valuation_for_growth=value_for_growth,
            lower_bound=-0.2,
            upper_bound=0.5,
            assumption_ids=assumption_ids,
        ),
        "growth_duration": solve_implied_assumption(
            ticker=request.ticker,
            market_price=inputs.market_price,
            valuation_for_assumption=value_for_duration,
            solved_variable="growth_duration",
            lower_bound=0.0,
            upper_bound=float(len(growth_by_year)),
            assumption_ids=assumption_ids,
        ),
        "operating_margin": solve_implied_assumption(
            ticker=request.ticker,
            market_price=inputs.market_price,
            valuation_for_assumption=value_for_margin,
            solved_variable="operating_margin",
            lower_bound=0.01,
            upper_bound=0.6,
            assumption_ids=assumption_ids,
        ),
    }
    current = statements.adjusted_periods[-1]
    comparables = calculate_comparables(
        ticker=request.ticker,
        peers=list(inputs.peers),
        selection_rationale="Peers share operating economics and end-market exposure.",
        target_revenue=current.revenue,
        target_ebitda=current.operating_income + current.depreciation_amortization,
        target_ebit=current.operating_income,
        target_net_income=current.net_income,
        target_fcf=current.cash_from_operations - current.capital_expenditure,
        target_net_debt=Decimal(str(metrics.net_debt)),
        target_shares=current.diluted_shares,
    )
    acquisition_warning = metrics.acquisition_intensity > 0.1
    accrual_warning = metrics.accrual_ratio is not None and metrics.accrual_ratio > 0.04
    sbc_warning = metrics.sbc_dilution > 0.1
    accounting_score = _clamp(
        1.0
        - 0.5 * float(accrual_warning)
        - 0.25 * float(sbc_warning)
        - 0.25 * float(acquisition_warning)
    )
    accounting = AccountingQualityAssessment(
        score=max(0.0, accounting_score),
        accrual_warning=accrual_warning,
        sbc_warning=sbc_warning,
        acquisition_warning=acquisition_warning,
        one_time_adjustments=[],
        findings=[
            *[
                name
                for active, name in (
                    (accrual_warning, "high accruals"),
                    (sbc_warning, "high stock-based compensation"),
                    (acquisition_warning, "acquisition intensity"),
                )
                if active
            ],
            *(
                [specialist_text["accounting_quality"]]
                if "accounting_quality" in specialist_text
                else []
            ),
        ],
        evidence_ids=list(inputs.evidence_ids),
        calculation_ids=metrics.calculation_ids,
    )
    business = BusinessModelAssessment(
        summary=specialist_text.get(
            "business_industry",
            (
                f"{request.company_name} is assessed through verified general-company "
                "operating drivers."
            ),
        ),
        revenue_drivers=list(inputs.revenue_driver_descriptions),
        moat_evidence=[],
        vulnerabilities=list(inputs.risks),
        evidence_ids=list(inputs.evidence_ids),
    )
    industry = IndustryAssessment(
        industry=inputs.industry,
        structure=specialist_text.get(
            "business_industry",
            "competitive structure assessed from the frozen evidence pack",
        ),
        cycle_position="point-in-time cycle state recorded in the research inputs",
        competitors=list(inputs.competitors),
        evidence_ids=list(inputs.evidence_ids),
    )
    valuation_signal = _clamp(scenario_valuation.implied_return)
    quality_signal = _clamp((metrics.roic or 0.0) * 3 + metrics.operating_margin)
    growth_signal = _clamp(metrics.revenue_growth * 3 + metrics.margin_change * 2)
    accounting_signal = _clamp(accounting.score * 2 - 1)
    balance_signal = _clamp(1 - max(0.0, metrics.debt_to_ebitda or 0.0) / 5)
    capital_signal = _clamp(metrics.net_buyback_yield * 5 - metrics.acquisition_intensity)
    management_hit_rate = 0.5 if management.hit_rate is None else management.hit_rate
    management_signal = _clamp(management_hit_rate * 2 - 1)
    profitability_signal = _clamp(metrics.operating_margin * 3)
    cash_signal = _clamp((metrics.cash_conversion or 0.0) * 0.5)
    base_revenue_growth = sum(growth_by_year.values()) / len(growth_by_year)
    implied_growth = reverse_dcf["revenue_growth"].implied_value
    expectations_gap_signal = _clamp(
        base_revenue_growth - implied_growth if implied_growth is not None else 0.0
    )
    catalyst_signal = _clamp(0.15 * (len(inputs.catalysts) - len(inputs.risks)))
    uncertainty = min(
        0.95,
        max(0.05, 0.5 - accounting_signal * 0.2 - len(inputs.evidence_ids) * 0.02),
    )
    components = [
        quality_signal,
        growth_signal,
        profitability_signal,
        accounting_signal,
        balance_signal,
        cash_signal,
        capital_signal,
        management_signal,
        valuation_signal,
        expectations_gap_signal,
        catalyst_signal,
    ]
    composite = sum(components) / len(components)
    scorecard_values = {
        "quality": quality_signal,
        "growth": growth_signal,
        "profitability": profitability_signal,
        "accounting": accounting_signal,
        "balance_sheet": balance_signal,
        "cash_conversion": cash_signal,
        "capital_allocation": capital_signal,
        "management": management_signal,
        "valuation": valuation_signal,
        "expectations_gap": expectations_gap_signal,
        "catalyst": catalyst_signal,
        "uncertainty": uncertainty,
    }
    scorecard_component_ids = [f"fundamental-scorecard-v1:{name}" for name in scorecard_values]
    metric_id_by_name = {
        calculation_id.rsplit(":", 1)[-1]: calculation_id
        for calculation_id in metrics.calculation_ids
    }
    scorecard_dependency_ids = {
        "quality": [metric_id_by_name["roic"], metric_id_by_name["operating_margin"]],
        "growth": [
            metric_id_by_name["revenue_growth"],
            metric_id_by_name["margin_change"],
        ],
        "profitability": [metric_id_by_name["operating_margin"]],
        "accounting": [
            metric_id_by_name["accrual_ratio"],
            metric_id_by_name["sbc_dilution"],
            metric_id_by_name["acquisition_intensity"],
        ],
        "balance_sheet": [metric_id_by_name["debt_to_ebitda"]],
        "cash_conversion": [metric_id_by_name["cash_conversion"]],
        "capital_allocation": [
            metric_id_by_name["net_buyback_yield"],
            metric_id_by_name["acquisition_intensity"],
        ],
        "management": list(management.calculation_ids),
        "valuation": [scenario_valuation.calculation_ids[1]],
        "expectations_gap": [reverse_dcf["revenue_growth"].calculation_ids[0]],
        "catalyst": [],
        "uncertainty": [
            metric_id_by_name["accrual_ratio"],
            metric_id_by_name["sbc_dilution"],
            metric_id_by_name["acquisition_intensity"],
        ],
    }
    scorecard_formulas = {
        "quality": "clamp(3 * ROIC + operating_margin)",
        "growth": "clamp(3 * revenue_growth + 2 * margin_change)",
        "profitability": "clamp(3 * operating_margin)",
        "accounting": "clamp(2 * accounting_quality_score - 1)",
        "balance_sheet": "clamp(1 - max(0, debt_to_ebitda) / 5)",
        "cash_conversion": "clamp(0.5 * cash_conversion)",
        "capital_allocation": "clamp(5 * net_buyback_yield - acquisition_intensity)",
        "management": "clamp(2 * guidance_hit_rate_or_neutral - 1)",
        "valuation": "clamp(probability_weighted_value / market_price - 1)",
        "expectations_gap": "clamp(base_forecast_growth - reverse_dcf_implied_growth)",
        "catalyst": "clamp(0.15 * (known_catalyst_count - known_risk_count))",
        "uncertainty": "bounded evidence and accounting-quality uncertainty",
    }
    scorecard = FundamentalScorecard(
        ticker=request.ticker,
        quality=quality_signal,
        growth=growth_signal,
        profitability=profitability_signal,
        accounting=accounting_signal,
        balance_sheet=balance_signal,
        cash_conversion=cash_signal,
        capital_allocation=capital_signal,
        management=management_signal,
        valuation=valuation_signal,
        expectations_gap=valuation_signal,
        catalyst=catalyst_signal,
        uncertainty=uncertainty,
        composite=composite,
        calculation_ids=[
            *metrics.calculation_ids,
            *scorecard_component_ids,
            "fundamental-scorecard-v1:deterministic-composite",
        ],
    )
    thesis_statement = (
        f"{request.company_name} combines a {metrics.revenue_growth:.1%} latest revenue "
        f"growth rate with {metrics.operating_margin:.1%} operating margin; the "
        f"probability-weighted valuation implies {scenario_valuation.implied_return:.1%}."
    )
    if specialist_text:
        challenge = " ".join(
            f"{role}: {statement}"
            for role, statement in sorted(specialist_text.items())
            if role != "business_industry"
        )
        if challenge:
            thesis_statement = f"{thesis_statement} Specialist review: {challenge}"
    thesis: InvestmentThesis = build_thesis(
        thesis_id=f"thesis-{request.request_id}-v1",
        ticker=request.ticker,
        version=1,
        as_of=request.as_of,
        horizon_days=request.horizon_days,
        core_claims=[
            ThesisClaim(
                claim_id=f"thesis-{request.request_id}-core",
                statement=thesis_statement,
                status="active",
                evidence_ids=list(inputs.evidence_ids),
                calculation_ids=scorecard.calculation_ids,
            )
        ],
        catalysts=list(inputs.catalysts),
        risks=list(inputs.risks),
        invalidation_conditions=[
            "base-case revenue or operating-margin checkpoint misses materially",
            "evidence or statement reconciliation fails",
        ],
        valuation_case_ids=[item.valuation_id for item in dcf.values()],
        checkpoints=[
            ThesisCheckpoint(
                checkpoint_id=f"checkpoint-{request.request_id}-horizon",
                due_at=request.as_of + timedelta(days=request.horizon_days),
                condition="compare realised operations and return with the base case",
                status="pending",
                evidence_ids=[],
            )
        ],
        supersedes_thesis_id=None,
        status="active",
        contract_version="3.0.0",
    )
    horizon_years = request.horizon_days / 365.0
    horizon_total_return = (
        scenario_valuation.implied_return + metrics.dividend_yield * horizon_years
    )
    annualized_expected_return = (
        (1 + horizon_total_return) ** (1 / horizon_years) - 1 if horizon_total_return > -1 else -1.0
    )
    raw_probability_positive = sum(
        inputs.scenario_probabilities[name]
        for name in ("bear", "base", "bull")
        if dcf[name].value_per_share > inputs.market_price
    )
    annualized_expected_return = (
        inputs.calibration.return_intercept
        + inputs.calibration.return_slope * annualized_expected_return
    )
    probability_positive = min(
        1.0,
        max(
            0.0,
            inputs.calibration.probability_intercept
            + inputs.calibration.probability_slope * raw_probability_positive,
        ),
    )
    calibration_uncertainty = min(
        0.95,
        inputs.calibration.root_mean_squared_error + inputs.calibration.brier_score / 2,
    )
    uncertainty = max(uncertainty, calibration_uncertainty)
    confidence = 1 - uncertainty
    alpha = AlphaForecast(
        forecast_id=f"fundamental-alpha-{request.request_id}",
        model_name="fundamental-alpha-v1",
        ticker=request.ticker,
        as_of=request.as_of,
        horizon_days=request.horizon_days,
        expected_excess_return=annualized_expected_return,
        expected_volatility=inputs.expected_volatility,
        probability_positive=min(1.0, max(0.0, probability_positive)),
        confidence=confidence,
        uncertainty=1 - confidence,
        downside_case=float(dcf["bear"].value_per_share / inputs.market_price - Decimal("1")),
        base_case=float(dcf["base"].value_per_share / inputs.market_price - Decimal("1")),
        upside_case=float(dcf["bull"].value_per_share / inputs.market_price - Decimal("1")),
        thesis=thesis_statement,
        evidence_ids=list(inputs.evidence_ids),
        invalidation_conditions=thesis.invalidation_conditions,
        catalyst_dates=[],
        thesis_expiry=request.as_of + timedelta(days=request.horizon_days),
        abstained=False,
        abstain_reason=None,
        components={
            "quality": quality_signal,
            "growth": growth_signal,
            "accounting": accounting_signal,
            "valuation": valuation_signal,
            "composite": composite,
        },
        metadata={
            "provider": "fundamental-research-v3",
            "scorecard": "v1",
            "calibration_id": inputs.calibration.calibration_id,
        },
    )
    guidance_assumptions = [f"guidance:{item.guidance_id}" for item in management.guidance]
    extra_lineage = [
        _derived_lineage(
            "management-track-v1:dilution",
            "management-track",
            "diluted_shares_t / diluted_shares_t-1 - 1",
            "dilution_rate",
            management.dilution_rate,
            input_calculation_ids=metrics.calculation_ids,
        ),
        _derived_lineage(
            "management-track-v1:disclosure-quality",
            "management-track",
            "matured_guidance / eligible_guidance",
            "disclosure_quality",
            management.disclosure_quality,
            input_calculation_ids=[],
            input_assumption_ids=guidance_assumptions or ["guidance:none-eligible"],
        ),
    ]
    extra_lineage.append(
        _derived_lineage(
            "management-track-v1:guidance-revision-count",
            "management-track",
            "count(eligible guidance records with supersedes_guidance_id)",
            "guidance_revision_count",
            float(management.guidance_revision_count),
            input_calculation_ids=[],
            input_assumption_ids=guidance_assumptions or ["guidance:none-eligible"],
        )
    )
    action_assumptions = [action.action_id for action in inputs.management_actions]
    for calculation_id, output_name, output_value in (
        (
            "management-track-v1:acquisition-return",
            "acquisition_return",
            management.acquisition_return,
        ),
        (
            "management-track-v1:buyback-timing-return",
            "buyback_timing_return",
            management.buyback_timing_return,
        ),
        (
            "management-track-v1:capital-allocation-follow-through",
            "capital_allocation_follow_through",
            management.capital_allocation_follow_through,
        ),
    ):
        if output_value is not None:
            extra_lineage.append(
                _derived_lineage(
                    calculation_id,
                    "management-track",
                    f"point-in-time eligible management actions -> {output_name}",
                    output_name,
                    output_value,
                    input_calculation_ids=[],
                    input_assumption_ids=action_assumptions,
                )
            )
    if management.matured_count:
        assert management.hit_rate is not None
        assert management.mean_bias is not None
        assert management.mean_absolute_error is not None
        extra_lineage.extend(
            [
                _derived_lineage(
                    "management-track-v1:guidance-hit-rate",
                    "management-track",
                    "guidance_hits / matured_guidance",
                    "guidance_hit_rate",
                    management.hit_rate,
                    input_calculation_ids=[],
                    input_assumption_ids=guidance_assumptions,
                ),
                _derived_lineage(
                    "management-track-v1:guidance-bias",
                    "management-track",
                    "mean(actual - guidance_midpoint)",
                    "guidance_bias",
                    management.mean_bias,
                    input_calculation_ids=[],
                    input_assumption_ids=guidance_assumptions,
                ),
                _derived_lineage(
                    "management-track-v1:guidance-mae",
                    "management-track",
                    "mean(abs(actual - guidance_midpoint))",
                    "guidance_mean_absolute_error",
                    management.mean_absolute_error,
                    input_calculation_ids=[],
                    input_assumption_ids=guidance_assumptions,
                ),
            ]
        )
    extra_lineage.extend(
        [
            *[
                _derived_lineage(
                    calculation_id,
                    "comparable-valuation",
                    "aggregate peer multiple distributions against target fundamentals",
                    f"comparable_value_{label}",
                    output_value,
                    input_calculation_ids=metrics.calculation_ids,
                    input_assumption_ids=[
                        f"peer:{peer.ticker}:multiples" for peer in comparables.peers
                    ],
                    unit="USD/share",
                )
                for calculation_id, label, output_value in zip(
                    comparables.calculation_ids,
                    ("low", "mid", "high"),
                    (
                        comparables.implied_value_low,
                        comparables.implied_value_mid,
                        comparables.implied_value_high,
                    ),
                    strict=True,
                )
            ],
            *[
                _derived_lineage(
                    result.calculation_ids[0],
                    "reverse-dcf-bisection",
                    "solve(DCF(assumption) - market_price = 0)",
                    result.solved_variable if result.feasible else "feasible",
                    result.implied_value if result.implied_value is not None else 0.0,
                    input_calculation_ids=dcf["base"].calculation_ids,
                    input_assumption_ids=result.assumption_ids,
                )
                for result in reverse_dcf.values()
            ],
            _derived_lineage(
                scenario_valuation.calculation_ids[0],
                "scenario-valuation",
                "sum(probability_s * value_per_share_s)",
                "probability_weighted_value",
                scenario_valuation.probability_weighted_value,
                input_calculation_ids=[
                    dcf[name].calculation_ids[-1] for name in ("bear", "base", "bull")
                ],
                input_assumption_ids=[
                    f"scenario-probability:{name}" for name in ("bear", "base", "bull")
                ],
                unit="USD/share",
            ),
            _derived_lineage(
                scenario_valuation.calculation_ids[1],
                "scenario-valuation",
                "probability_weighted_value / market_price - 1",
                "scenario_implied_return",
                scenario_valuation.implied_return,
                input_calculation_ids=[scenario_valuation.calculation_ids[0]],
                input_assumption_ids=[f"{request.request_id}:market-price"],
            ),
            *[
                _derived_lineage(
                    calculation_id,
                    "fundamental-scorecard",
                    scorecard_formulas[name],
                    name,
                    value,
                    input_calculation_ids=sorted(set(scorecard_dependency_ids[name])),
                    input_assumption_ids=[inputs.content_hash],
                )
                for calculation_id, (name, value) in zip(
                    scorecard_component_ids,
                    scorecard_values.items(),
                    strict=True,
                )
            ],
            _derived_lineage(
                "fundamental-scorecard-v1:deterministic-composite",
                "fundamental-scorecard",
                "mean(component_scores)",
                "fundamental_composite",
                composite,
                input_calculation_ids=scorecard_component_ids,
                input_assumption_ids=[inputs.content_hash],
            ),
            _derived_lineage(
                "fundamental-alpha-v1:calibrated-expected-return",
                "fundamental-alpha-calibration",
                "return_intercept + return_slope * annualized_raw_return",
                "expected_excess_return",
                annualized_expected_return,
                input_calculation_ids=[
                    scenario_valuation.calculation_ids[1],
                    next(
                        item for item in metrics.calculation_ids if item.endswith(":dividend_yield")
                    ),
                ],
                input_assumption_ids=[
                    inputs.calibration.calibration_id,
                    f"{request.request_id}:horizon-days:{request.horizon_days}",
                ],
            ),
            _derived_lineage(
                "fundamental-alpha-v1:calibrated-probability",
                "fundamental-alpha-calibration",
                "clip(probability_intercept + probability_slope * raw_probability)",
                "probability_positive",
                probability_positive,
                input_calculation_ids=[
                    dcf[name].calculation_ids[-1] for name in ("bear", "base", "bull")
                ],
                input_assumption_ids=[
                    inputs.calibration.calibration_id,
                    f"{request.request_id}:market-price",
                ],
            ),
            _derived_lineage(
                "fundamental-alpha-v1:calibrated-confidence",
                "fundamental-alpha-calibration",
                "1 - max(evidence_uncertainty, calibration_error_uncertainty)",
                "confidence",
                confidence,
                input_calculation_ids=[
                    "fundamental-scorecard-v1:uncertainty",
                ],
                input_assumption_ids=[
                    inputs.calibration.calibration_id,
                    inputs.content_hash,
                ],
            ),
        ]
    )
    all_lineage = [
        *statements.calculation_lineage,
        *metric_lineage,
        *forecast_lineage,
        *dcf_lineage,
        *extra_lineage,
    ]
    all_calculation_ids = sorted(item.calculation_id for item in all_lineage)
    sotp = SOTPResult(
        valuation_id=f"sotp-{request.request_id}",
        ticker=request.ticker,
        supported=False,
        segments=[],
        total_enterprise_value=None,
        abstain_reason="valid segment-level valuation inputs were not supplied",
        calculation_ids=[],
    )
    values = {
        "dossier_id": f"fundamental-dossier-{request.request_id}",
        "request": request,
        "archetype": archetype,
        "source_snapshot_hash": snapshot.content_hash,
        "input_snapshot_hash": inputs.content_hash,
        "input_evidence": inputs.evidence,
        "statements": statements,
        "metrics": metrics,
        "business": business,
        "industry": industry,
        "accounting": accounting,
        "management": management,
        "forecasts": forecasts,
        "dcf": dcf,
        "reverse_dcf": reverse_dcf,
        "comparables": comparables,
        "sotp": sotp,
        "scenario_valuation": scenario_valuation,
        "scorecard": scorecard,
        "thesis": thesis,
        "alpha_forecast": alpha,
        "specialist_artifacts": list(specialist_artifacts),
        "specialist_findings": {
            artifact.role: [claim.statement for claim in artifact.claims]
            for artifact in specialist_artifacts
        },
        "release_status": "preliminary",
        "committee_decision": None,
        "evidence_ids": sorted(inputs.evidence_ids),
        "calculation_ids": all_calculation_ids,
        "calculation_lineage": sorted(all_lineage, key=lambda item: item.calculation_id),
        "known_gaps": [
            "SOTP abstained without valid segment inputs",
            "peer valuation is contextual rather than a precise target",
        ],
        "abstained": False,
        "abstain_reason": None,
        "contract_version": "3.0.0",
    }
    return build_hashed(FundamentalResearchDossier, **values)
