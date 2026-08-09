"""Pure deterministic fundamental metrics with calculation lineage."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from aegis.contracts import (
    CalculationLineage,
    FinancialPeriod,
    FundamentalMetrics,
    NormalizedFinancialStatements,
)

from .hashing import build_hashed


@dataclass(frozen=True)
class _FloatPeriod:
    fiscal_year: int
    revenue: float
    cost_of_revenue: float
    operating_expenses: float
    operating_income: float
    interest_expense: float
    tax_expense: float
    net_income: float
    diluted_shares: float
    cash: float
    current_assets: float
    current_liabilities: float
    total_assets: float
    total_debt: float
    total_equity: float
    cash_from_operations: float
    capital_expenditure: float
    depreciation_amortization: float
    stock_based_compensation: float
    acquisitions: float
    dividends: float
    share_repurchases: float
    share_issuance: float
    working_capital: float

    @classmethod
    def from_exact(cls, period: FinancialPeriod) -> _FloatPeriod:
        return cls(
            fiscal_year=period.fiscal_year,
            revenue=float(period.revenue),
            cost_of_revenue=float(period.cost_of_revenue),
            operating_expenses=float(period.operating_expenses),
            operating_income=float(period.operating_income),
            interest_expense=float(period.interest_expense),
            tax_expense=float(period.tax_expense),
            net_income=float(period.net_income),
            diluted_shares=float(period.diluted_shares),
            cash=float(period.cash),
            current_assets=float(period.current_assets),
            current_liabilities=float(period.current_liabilities),
            total_assets=float(period.total_assets),
            total_debt=float(period.total_debt),
            total_equity=float(period.total_equity),
            cash_from_operations=float(period.cash_from_operations),
            capital_expenditure=float(period.capital_expenditure),
            depreciation_amortization=float(period.depreciation_amortization),
            stock_based_compensation=float(period.stock_based_compensation),
            acquisitions=float(period.acquisitions),
            dividends=float(period.dividends),
            share_repurchases=float(period.share_repurchases),
            share_issuance=float(period.share_issuance),
            working_capital=float(period.working_capital),
        )


class MetricCalculationError(RuntimeError):
    pass


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if abs(denominator) <= 1e-12 else numerator / denominator


def _fact_ids(periods: Iterable[FinancialPeriod], names: Iterable[str]) -> list[str]:
    values = {
        fact_id
        for period in periods
        for name in names
        for fact_id in period.lineage_by_line_item.get(name, [])
    }
    return sorted(values)


def _lineage(
    name: str,
    value: Decimal | float | None,
    formula: str,
    periods: list[FinancialPeriod],
    inputs: list[str],
    input_assumption_ids: list[str] | None = None,
) -> CalculationLineage | None:
    if value is None:
        return None
    values = {
        "calculation_id": f"fundamental-metrics-v1:{periods[-1].period_end}:{name}",
        "calculator": "fundamental-metrics",
        "calculator_version": "1.0.0",
        "formula": formula,
        "input_fact_ids": _fact_ids(periods, inputs),
        "input_calculation_ids": [],
        "input_assumption_ids": input_assumption_ids or [],
        "output_name": name,
        "output_value": value,
        "unit": (
            "USD/share"
            if name == "fcf_per_share"
            else "USD"
            if name in {"net_debt", "working_capital_change", "debt_change"}
            else "ratio"
        ),
        "contract_version": "3.0.0",
    }
    return build_hashed(CalculationLineage, **values)


def calculate_metrics(
    statements: NormalizedFinancialStatements,
    *,
    market_price: Decimal,
) -> tuple[FundamentalMetrics, tuple[CalculationLineage, ...]]:
    if market_price <= 0:
        raise MetricCalculationError("market price must be positive")
    source_periods = statements.adjusted_periods
    periods = [_FloatPeriod.from_exact(period) for period in source_periods]
    if len(periods) < 2:
        raise MetricCalculationError("at least two aligned periods are required")
    previous, current = periods[-2], periods[-1]
    earlier = periods[-3] if len(periods) >= 3 else None
    revenue_growth = current.revenue / previous.revenue - 1
    year_span = max(1, current.fiscal_year - periods[0].fiscal_year)
    revenue_cagr = (current.revenue / periods[0].revenue) ** (1 / year_span) - 1
    eps_current = current.net_income / current.diluted_shares
    eps_previous = previous.net_income / previous.diluted_shares
    eps_growth = _ratio(eps_current - eps_previous, abs(eps_previous))
    fcf_current = current.cash_from_operations - current.capital_expenditure
    fcf_previous = previous.cash_from_operations - previous.capital_expenditure
    fcf_growth = _ratio(fcf_current - fcf_previous, abs(fcf_previous))
    growth_acceleration = None
    if earlier is not None:
        prior_growth = previous.revenue / earlier.revenue - 1
        growth_acceleration = revenue_growth - prior_growth
    gross_margin = (current.revenue - current.cost_of_revenue) / current.revenue
    operating_margin = current.operating_income / current.revenue
    ebitda = current.operating_income + current.depreciation_amortization
    ebitda_margin = ebitda / current.revenue
    prior_margin = previous.operating_income / previous.revenue
    margin_change = operating_margin - prior_margin
    revenue_change = current.revenue - previous.revenue
    operating_leverage = _ratio(
        current.operating_income - previous.operating_income, revenue_change
    )
    pretax_income = current.net_income + current.tax_expense
    effective_tax = min(1.0, max(0.0, _ratio(current.tax_expense, pretax_income) or 0.0))
    nopat = current.operating_income * (1 - effective_tax)
    prior_pretax = previous.net_income + previous.tax_expense
    prior_tax = min(1.0, max(0.0, _ratio(previous.tax_expense, prior_pretax) or 0.0))
    prior_nopat = previous.operating_income * (1 - prior_tax)
    invested = current.total_debt + current.total_equity - current.cash
    prior_invested = previous.total_debt + previous.total_equity - previous.cash
    roic = _ratio(nopat, invested)
    incremental_roic = _ratio(nopat - prior_nopat, invested - prior_invested)
    roe = _ratio(current.net_income, (current.total_equity + previous.total_equity) / 2)
    asset_turns = _ratio(current.revenue, (current.total_assets + previous.total_assets) / 2)
    reinvestment = (
        current.capital_expenditure
        - current.depreciation_amortization
        + current.working_capital
        - previous.working_capital
    )
    reinvestment_rate = _ratio(reinvestment, nopat)
    cash_conversion = _ratio(fcf_current, current.net_income)
    cfo_to_net_income = _ratio(current.cash_from_operations, current.net_income)
    accrual_ratio = _ratio(
        current.net_income - current.cash_from_operations,
        (current.total_assets + previous.total_assets) / 2,
    )
    working_capital_to_revenue = current.working_capital / current.revenue
    working_capital_change = source_periods[-1].working_capital - source_periods[-2].working_capital
    cash_tax_rate = _ratio(current.tax_expense, pretax_income)
    sbc_dilution = current.stock_based_compensation / current.revenue
    capex_intensity = current.capital_expenditure / current.revenue
    net_debt = source_periods[-1].total_debt - source_periods[-1].cash
    debt_to_ebitda = _ratio(current.total_debt, ebitda)
    interest_coverage = _ratio(current.operating_income, current.interest_expense)
    current_ratio = _ratio(current.current_assets, current.current_liabilities)
    cash_burn = max(0.0, -current.cash_from_operations)
    liquidity_runway_years = _ratio(current.cash, cash_burn) if cash_burn else None
    debt_change = source_periods[-1].total_debt - source_periods[-2].total_debt
    market_cap = source_periods[-1].diluted_shares * market_price
    net_buyback_yield = float(
        (source_periods[-1].share_repurchases - source_periods[-1].share_issuance) / market_cap
    )
    dividend_payout = _ratio(current.dividends, current.net_income)
    dividend_yield = float(source_periods[-1].dividends / market_cap)
    acquisition_intensity = current.acquisitions / current.revenue
    fcf_per_share = (
        source_periods[-1].cash_from_operations - source_periods[-1].capital_expenditure
    ) / source_periods[-1].diluted_shares
    metric_values: dict[str, Decimal | float | None] = {
        "revenue_growth": revenue_growth,
        "revenue_cagr": revenue_cagr,
        "eps_growth": eps_growth,
        "fcf_growth": fcf_growth,
        "growth_acceleration": growth_acceleration,
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "ebitda_margin": ebitda_margin,
        "margin_change": margin_change,
        "operating_leverage": operating_leverage,
        "roic": roic,
        "incremental_roic": incremental_roic,
        "roe": roe,
        "asset_turns": asset_turns,
        "reinvestment_rate": reinvestment_rate,
        "cash_conversion": cash_conversion,
        "cfo_to_net_income": cfo_to_net_income,
        "accrual_ratio": accrual_ratio,
        "working_capital_to_revenue": working_capital_to_revenue,
        "working_capital_change": working_capital_change,
        "cash_tax_rate": cash_tax_rate,
        "sbc_dilution": sbc_dilution,
        "capex_intensity": capex_intensity,
        "net_debt": net_debt,
        "debt_to_ebitda": debt_to_ebitda,
        "interest_coverage": interest_coverage,
        "current_ratio": current_ratio,
        "liquidity_runway_years": liquidity_runway_years,
        "debt_change": debt_change,
        "net_buyback_yield": net_buyback_yield,
        "dividend_payout": dividend_payout,
        "dividend_yield": dividend_yield,
        "acquisition_intensity": acquisition_intensity,
        "fcf_per_share": fcf_per_share,
    }
    formulas = {
        "revenue_growth": "revenue_t / revenue_t-1 - 1",
        "revenue_cagr": "(revenue_t / revenue_first)^(1/year_span) - 1",
        "eps_growth": "growth(net_income / diluted_shares)",
        "fcf_growth": "growth(cash_from_operations - capital_expenditure)",
        "growth_acceleration": "revenue_growth_t - revenue_growth_t-1",
        "gross_margin": "(revenue - cost_of_revenue) / revenue",
        "operating_margin": "operating_income / revenue",
        "ebitda_margin": "(operating_income + D&A) / revenue",
        "margin_change": "operating_margin_t - operating_margin_t-1",
        "operating_leverage": "delta operating_income / delta revenue",
        "roic": "NOPAT / (debt + equity - cash)",
        "incremental_roic": "delta NOPAT / delta invested_capital",
        "roe": "net_income / average_equity",
        "asset_turns": "revenue / average_assets",
        "reinvestment_rate": "(capex - D&A + delta working_capital) / NOPAT",
        "cash_conversion": "FCF / net_income",
        "cfo_to_net_income": "cash_from_operations / net_income",
        "accrual_ratio": "(net_income - CFO) / average_assets",
        "working_capital_to_revenue": "working_capital / revenue",
        "working_capital_change": "working_capital_t - working_capital_t-1",
        "cash_tax_rate": "tax_expense / pretax_income",
        "sbc_dilution": "stock_based_compensation / revenue",
        "capex_intensity": "capital_expenditure / revenue",
        "net_debt": "total_debt - cash",
        "debt_to_ebitda": "total_debt / (operating_income + D&A)",
        "interest_coverage": "operating_income / interest_expense",
        "current_ratio": "current_assets / current_liabilities",
        "liquidity_runway_years": "cash / annual_cash_burn",
        "debt_change": "total_debt_t - total_debt_t-1",
        "net_buyback_yield": "(repurchases - issuance) / market_cap",
        "dividend_payout": "dividends / net_income",
        "dividend_yield": "dividends / market_cap",
        "acquisition_intensity": "acquisitions / revenue",
        "fcf_per_share": "FCF / diluted_shares",
    }
    input_names = list(source_periods[-1].lineage_by_line_item)
    lineages = tuple(
        lineage
        for name, value in metric_values.items()
        if (
            lineage := _lineage(
                name,
                value,
                formulas[name],
                list(source_periods),
                input_names,
                input_assumption_ids=(
                    [f"{statements.ticker}:{statements.as_of.isoformat()}:market-price"]
                    if name in {"net_buyback_yield", "dividend_yield"}
                    else []
                ),
            )
        )
        is not None
    )
    metrics = FundamentalMetrics(
        ticker=statements.ticker,
        as_of=statements.as_of,
        revenue_growth=revenue_growth,
        revenue_cagr=revenue_cagr,
        organic_revenue_growth=None,
        acquired_revenue_growth=None,
        eps_growth=eps_growth,
        fcf_growth=fcf_growth,
        growth_acceleration=growth_acceleration,
        gross_margin=gross_margin,
        operating_margin=operating_margin,
        ebitda_margin=ebitda_margin,
        margin_change=margin_change,
        operating_leverage=operating_leverage,
        roic=roic,
        incremental_roic=incremental_roic,
        roe=roe,
        asset_turns=asset_turns,
        reinvestment_rate=reinvestment_rate,
        cash_conversion=cash_conversion,
        cfo_to_net_income=cfo_to_net_income,
        accrual_ratio=accrual_ratio,
        working_capital_to_revenue=working_capital_to_revenue,
        working_capital_change=working_capital_change,
        cash_tax_rate=cash_tax_rate,
        sbc_dilution=sbc_dilution,
        capex_intensity=capex_intensity,
        net_debt=net_debt,
        debt_to_ebitda=debt_to_ebitda,
        interest_coverage=interest_coverage,
        current_ratio=current_ratio,
        liquidity_runway_years=liquidity_runway_years,
        debt_change=debt_change,
        net_buyback_yield=net_buyback_yield,
        dividend_payout=dividend_payout,
        dividend_yield=dividend_yield,
        acquisition_intensity=acquisition_intensity,
        fcf_per_share=fcf_per_share,
        calculation_ids=[lineage.calculation_id for lineage in lineages],
    )
    return metrics, lineages
