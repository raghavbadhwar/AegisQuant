"""Point-in-time filing fact selection and reversible statement normalisation."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from aegis.contracts import (
    CalculationLineage,
    FilingFact,
    FinancialPeriod,
    NormalizationAdjustment,
    NormalizedFinancialStatements,
    RawFilingSnapshot,
)

from .hashing import build_hashed

_CONCEPTS: dict[str, str] = {
    "Revenue": "revenue",
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "CostOfRevenue": "cost_of_revenue",
    "CostOfGoodsAndServicesSold": "cost_of_revenue",
    "OperatingExpenses": "operating_expenses",
    "OperatingIncomeLoss": "operating_income",
    "InterestExpense": "interest_expense",
    "IncomeTaxExpenseBenefit": "tax_expense",
    "NetIncomeLoss": "net_income",
    "WeightedAverageNumberOfDilutedSharesOutstanding": "diluted_shares",
    "CashAndCashEquivalentsAtCarryingValue": "cash",
    "AssetsCurrent": "current_assets",
    "LiabilitiesCurrent": "current_liabilities",
    "Assets": "total_assets",
    "Liabilities": "total_liabilities",
    "LongTermDebtAndFinanceLeaseObligationsCurrent": "total_debt",
    "StockholdersEquity": "total_equity",
    "NetCashProvidedByUsedInOperatingActivities": "cash_from_operations",
    "IncreaseDecreaseInOperatingCapital": "cash_flow_working_capital_change",
    "OtherNoncashIncomeExpense": "other_operating_cash_adjustments",
    "PaymentsToAcquirePropertyPlantAndEquipment": "capital_expenditure",
    "DepreciationDepletionAndAmortization": "depreciation_amortization",
    "ShareBasedCompensation": "stock_based_compensation",
    "PaymentsToAcquireBusinessesNetOfCashAcquired": "acquisitions",
    "PaymentsOfDividends": "dividends",
    "PaymentsForRepurchaseOfCommonStock": "share_repurchases",
    "ProceedsFromStockOptionsExercised": "share_issuance",
    "WorkingCapital": "working_capital",
}
_REQUIRED = {
    "revenue",
    "cost_of_revenue",
    "operating_expenses",
    "interest_expense",
    "tax_expense",
    "net_income",
    "diluted_shares",
    "cash",
    "current_assets",
    "current_liabilities",
    "total_assets",
    "total_liabilities",
    "total_debt",
    "total_equity",
    "cash_from_operations",
    "cash_flow_working_capital_change",
    "other_operating_cash_adjustments",
    "capital_expenditure",
    "depreciation_amortization",
    "stock_based_compensation",
    "acquisitions",
    "dividends",
    "share_repurchases",
    "share_issuance",
}


class StatementNormalizationError(RuntimeError):
    pass


def _canonical(concept: str) -> str | None:
    return _CONCEPTS.get(concept, concept if concept in _CONCEPTS.values() else None)


def _lineage(
    calculation_id: str,
    formula: str,
    fact_ids: list[str],
    output_name: str,
    output_value: Decimal,
) -> CalculationLineage:
    values = {
        "calculation_id": calculation_id,
        "calculator": "general-company-normalizer",
        "calculator_version": "1.0.0",
        "formula": formula,
        "input_fact_ids": sorted(fact_ids),
        "input_calculation_ids": [],
        "output_name": output_name,
        "output_value": output_value,
        "unit": "USD",
        "contract_version": "3.0.0",
    }
    return build_hashed(CalculationLineage, **values)


def _select(snapshot: RawFilingSnapshot) -> dict[date, dict[str, FilingFact]]:
    selected: dict[date, dict[str, FilingFact]] = defaultdict(dict)
    for fact in sorted(
        snapshot.facts,
        key=lambda item: (item.period_end, item.concept, item.revision, item.accepted_at),
    ):
        if fact.statement_scope != "continuing_operations":
            continue
        canonical = _canonical(fact.concept)
        if canonical is None:
            continue
        current = selected[fact.period_end].get(canonical)
        if current is None or (fact.revision, fact.accepted_at, fact.fact_id) > (
            current.revision,
            current.accepted_at,
            current.fact_id,
        ):
            selected[fact.period_end][canonical] = fact
    return selected


def _validate_dimensions(facts: dict[str, FilingFact]) -> None:
    instant_concepts = {
        "cash",
        "current_assets",
        "current_liabilities",
        "total_assets",
        "total_liabilities",
        "total_debt",
        "total_equity",
        "working_capital",
    }
    for concept, fact in facts.items():
        expected_unit = "shares" if concept == "diluted_shares" else "USD"
        if fact.unit != expected_unit:
            raise StatementNormalizationError(
                f"filing concept {concept} has invalid unit {fact.unit}"
            )
        if fact.fiscal_period != "FY" or fact.form not in {"10-K", "10-K/A"}:
            raise StatementNormalizationError("general-company release requires annual 10-K facts")
        if concept in instant_concepts:
            if fact.period_start is not None:
                raise StatementNormalizationError(
                    f"instant filing concept {concept} must not have a duration"
                )
        else:
            if fact.period_start is None:
                raise StatementNormalizationError(
                    f"duration filing concept {concept} requires a period start"
                )
            duration_days = (fact.period_end - fact.period_start).days
            if not 300 <= duration_days <= 370:
                raise StatementNormalizationError(
                    f"annual filing concept {concept} has invalid duration"
                )


def _period(
    period_end: date, facts: dict[str, FilingFact]
) -> tuple[FinancialPeriod, list[CalculationLineage]]:
    _validate_dimensions(facts)
    missing = sorted(_REQUIRED.difference(facts))
    if missing:
        raise StatementNormalizationError(f"missing required filing concepts: {missing}")
    values = {name: facts[name].value for name in _REQUIRED}
    lineages: list[CalculationLineage] = []
    derived_operating = values["revenue"] - values["cost_of_revenue"] - values["operating_expenses"]
    if "operating_income" in facts:
        if abs(facts["operating_income"].value - derived_operating) > max(
            Decimal("1"), values["revenue"]
        ) * Decimal("1e-8"):
            raise StatementNormalizationError("reported operating income does not reconcile")
        operating_fact_ids = [facts["operating_income"].fact_id]
    else:
        operating_fact_ids = [
            facts[name].fact_id for name in ("revenue", "cost_of_revenue", "operating_expenses")
        ]
    lineages.append(
        _lineage(
            f"normalize:{period_end}:operating-income",
            "revenue - cost_of_revenue - operating_expenses",
            operating_fact_ids,
            "operating_income",
            derived_operating,
        )
    )
    working_capital = facts.get("working_capital")
    derived_wc = values["current_assets"] - values["current_liabilities"]
    if working_capital is not None and abs(working_capital.value - derived_wc) > max(
        Decimal("1"), values["total_assets"]
    ) * Decimal("1e-8"):
        raise StatementNormalizationError("reported working capital does not reconcile")
    wc_fact_ids = (
        [working_capital.fact_id]
        if working_capital is not None
        else [facts["current_assets"].fact_id, facts["current_liabilities"].fact_id]
    )
    lineages.append(
        _lineage(
            f"normalize:{period_end}:working-capital",
            "current_assets - current_liabilities",
            wc_fact_ids,
            "working_capital",
            derived_wc,
        )
    )
    lineage_by_line_item = {
        name: [fact.fact_id] for name, fact in facts.items() if name in _REQUIRED
    }
    lineage_by_line_item["operating_income"] = operating_fact_ids
    lineage_by_line_item["working_capital"] = wc_fact_ids
    fiscal_year = max(fact.fiscal_year for fact in facts.values())
    return (
        FinancialPeriod(
            period_end=period_end,
            fiscal_year=fiscal_year,
            revenue=values["revenue"],
            cost_of_revenue=values["cost_of_revenue"],
            operating_expenses=values["operating_expenses"],
            operating_income=derived_operating,
            interest_expense=values["interest_expense"],
            tax_expense=values["tax_expense"],
            net_income=values["net_income"],
            diluted_shares=values["diluted_shares"],
            cash=values["cash"],
            current_assets=values["current_assets"],
            current_liabilities=values["current_liabilities"],
            total_assets=values["total_assets"],
            total_liabilities=values["total_liabilities"],
            total_debt=values["total_debt"],
            total_equity=values["total_equity"],
            cash_from_operations=values["cash_from_operations"],
            cash_flow_working_capital_change=values["cash_flow_working_capital_change"],
            other_operating_cash_adjustments=values["other_operating_cash_adjustments"],
            capital_expenditure=values["capital_expenditure"],
            depreciation_amortization=values["depreciation_amortization"],
            stock_based_compensation=values["stock_based_compensation"],
            acquisitions=values["acquisitions"],
            dividends=values["dividends"],
            share_repurchases=values["share_repurchases"],
            share_issuance=values["share_issuance"],
            working_capital=derived_wc,
            lineage_by_line_item=lineage_by_line_item,
        ),
        lineages,
    )


def _adjust_period(
    reported: FinancialPeriod, adjustments: list[NormalizationAdjustment]
) -> FinancialPeriod:
    updates: dict[str, Decimal] = {}
    allowed = {
        "cost_of_revenue",
        "operating_expenses",
        "interest_expense",
        "tax_expense",
        "net_income",
        "cash_from_operations",
        "cash_flow_working_capital_change",
        "other_operating_cash_adjustments",
        "capital_expenditure",
        "stock_based_compensation",
        "acquisitions",
    }
    lineage_map = {name: list(ids) for name, ids in reported.lineage_by_line_item.items()}
    for adjustment in adjustments:
        if adjustment.line_item not in allowed:
            raise StatementNormalizationError(
                f"unsupported adjustment line item: {adjustment.line_item}"
            )
        current = updates.get(adjustment.line_item, getattr(reported, adjustment.line_item))
        updates[adjustment.line_item] = current + adjustment.amount
        lineage_map.setdefault(adjustment.line_item, []).append(
            f"calculation:normalize-adjustment:{adjustment.adjustment_id}"
        )
    cost = updates.get("cost_of_revenue", reported.cost_of_revenue)
    opex = updates.get("operating_expenses", reported.operating_expenses)
    updates["operating_income"] = reported.revenue - cost - opex
    net_income = updates.get("net_income", reported.net_income)
    cfo = updates.get("cash_from_operations", reported.cash_from_operations)
    depreciation = updates.get("depreciation_amortization", reported.depreciation_amortization)
    stock_compensation = updates.get("stock_based_compensation", reported.stock_based_compensation)
    working_capital_change = updates.get(
        "cash_flow_working_capital_change",
        reported.cash_flow_working_capital_change,
    )
    updates["other_operating_cash_adjustments"] = (
        cfo - net_income - depreciation - stock_compensation - working_capital_change
    )
    if adjustments:
        lineage_map["operating_income"] = [
            *lineage_map["operating_income"],
            *[
                f"calculation:normalize-adjustment:{item.adjustment_id}"
                for item in adjustments
                if item.line_item in {"cost_of_revenue", "operating_expenses"}
            ],
        ]
    return reported.model_copy(update={**updates, "lineage_by_line_item": lineage_map})


def normalize_statements(
    snapshot: RawFilingSnapshot,
    adjustments: list[NormalizationAdjustment] | None = None,
) -> NormalizedFinancialStatements:
    supplied_adjustments = list(adjustments or [])
    adjustable = {
        "cost_of_revenue",
        "operating_expenses",
        "interest_expense",
        "tax_expense",
        "net_income",
        "cash_from_operations",
        "cash_flow_working_capital_change",
        "other_operating_cash_adjustments",
        "capital_expenditure",
        "stock_based_compensation",
        "acquisitions",
    }
    detected_adjustments = []
    adjusted_fact_ids = {
        fact_id for adjustment in supplied_adjustments for fact_id in adjustment.evidence_fact_ids
    }
    for fact in snapshot.facts:
        line_item = _canonical(fact.concept)
        if (
            fact.is_one_time
            and fact.statement_scope == "continuing_operations"
            and line_item in adjustable
            and fact.fact_id not in adjusted_fact_ids
        ):
            detected_adjustments.append(
                NormalizationAdjustment(
                    adjustment_id=f"detected-one-time-{fact.fact_id}",
                    period_end=fact.period_end,
                    line_item=line_item,
                    amount=-fact.value,
                    reason="deterministically detected source-tagged one-time item",
                    adjustment_type="one_time_item",
                    evidence_fact_ids=[fact.fact_id],
                )
            )
    adjustments = sorted(
        [*supplied_adjustments, *detected_adjustments],
        key=lambda item: (item.period_end, item.adjustment_id),
    )
    selected = _select(snapshot)
    reported: list[FinancialPeriod] = []
    lineages: list[CalculationLineage] = []
    for period_end, facts in sorted(selected.items()):
        period, period_lineage = _period(period_end, facts)
        reported.append(period)
        lineages.extend(period_lineage)
    if len(reported) < 2:
        raise StatementNormalizationError("at least two annual periods are required")
    known_fact_ids = {fact.fact_id for fact in snapshot.facts}
    if any(
        not set(adjustment.evidence_fact_ids).issubset(known_fact_ids) for adjustment in adjustments
    ):
        raise StatementNormalizationError("adjustment cites facts outside the raw snapshot")
    by_period: dict[date, list[NormalizationAdjustment]] = defaultdict(list)
    for adjustment in adjustments:
        by_period[adjustment.period_end].append(adjustment)
    known_periods = {period.period_end for period in reported}
    if not set(by_period).issubset(known_periods):
        raise StatementNormalizationError("adjustment period is outside normalized statements")
    adjusted = [_adjust_period(period, by_period[period.period_end]) for period in reported]
    adjusted_by_period = {period.period_end: period for period in adjusted}
    for adjustment in adjustments:
        output_value = getattr(adjusted_by_period[adjustment.period_end], adjustment.line_item)
        values = {
            "calculation_id": f"normalize-adjustment:{adjustment.adjustment_id}",
            "calculator": "general-company-normalizer",
            "calculator_version": "1.0.0",
            "formula": f"reported_{adjustment.line_item} + adjustment_amount",
            "input_fact_ids": sorted(adjustment.evidence_fact_ids),
            "input_calculation_ids": [],
            "input_assumption_ids": [f"normalization-adjustment:{adjustment.adjustment_id}"],
            "output_name": adjustment.line_item,
            "output_value": output_value,
            "unit": "USD",
            "contract_version": "3.0.0",
        }
        lineages.append(build_hashed(CalculationLineage, **values))
    for period_end, period_adjustments in sorted(by_period.items()):
        operating_adjustments = [
            item
            for item in period_adjustments
            if item.line_item in {"cost_of_revenue", "operating_expenses"}
        ]
        if not operating_adjustments:
            continue
        values = {
            "calculation_id": f"normalize-adjusted-operating-income:{period_end}",
            "calculator": "general-company-normalizer",
            "calculator_version": "1.0.0",
            "formula": "adjusted_revenue - adjusted_cost_of_revenue - adjusted_operating_expenses",
            "input_fact_ids": [],
            "input_calculation_ids": [
                f"normalize:{period_end}:operating-income",
                *[f"normalize-adjustment:{item.adjustment_id}" for item in operating_adjustments],
            ],
            "input_assumption_ids": [],
            "output_name": "operating_income",
            "output_value": adjusted_by_period[period_end].operating_income,
            "unit": "USD",
            "contract_version": "3.0.0",
        }
        lineages.append(build_hashed(CalculationLineage, **values))
    values = {
        "statements_id": f"statements-{snapshot.snapshot_id}",
        "ticker": snapshot.ticker,
        "as_of": snapshot.as_of,
        "reported_periods": reported,
        "adjusted_periods": adjusted,
        "adjustments": adjustments,
        "calculation_lineage": lineages,
        "source_snapshot_hash": snapshot.content_hash,
        "normalizer_version": "general-company-normalizer-v1",
        "contract_version": "3.0.0",
    }
    return build_hashed(NormalizedFinancialStatements, **values)


def reverse_adjustments(statements: NormalizedFinancialStatements) -> list[FinancialPeriod]:
    """Return the immutable reported view; analytical adjustments never overwrite it."""
    return list(statements.reported_periods)


def raw_snapshot(
    snapshot_id: str,
    ticker: str,
    as_of: datetime,
    facts: list[FilingFact],
    raw_receipt_ids: list[str],
    source_manifest_versions: dict[str, str],
) -> RawFilingSnapshot:
    values = {
        "snapshot_id": snapshot_id,
        "ticker": ticker,
        "as_of": as_of,
        "facts": facts,
        "raw_receipt_ids": raw_receipt_ids,
        "source_manifest_versions": source_manifest_versions,
        "contract_version": "3.0.0",
    }
    return build_hashed(RawFilingSnapshot, **values)
