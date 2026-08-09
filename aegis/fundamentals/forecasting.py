"""Driver-based deterministic operating-statement forecasting."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from aegis.contracts import (
    CalculationLineage,
    FinancialPeriod,
    ForecastDriver,
    ForecastPeriod,
    NormalizedFinancialStatements,
    OperatingForecast,
)

from .hashing import build_hashed

_REQUIRED_DRIVERS = {
    "revenue_growth",
    "operating_margin",
    "tax_rate",
    "reinvestment_rate",
    "share_dilution",
}


class ForecastCalculationError(RuntimeError):
    pass


def _lineage(
    scenario: str,
    year: int,
    output_name: str,
    value: Decimal,
    formula: str,
    input_calculation_ids: list[str],
    input_assumption_ids: list[str],
) -> CalculationLineage:
    values = {
        "calculation_id": f"operating-forecast-v1:{scenario}:{year}:{output_name}",
        "calculator": "operating-forecast",
        "calculator_version": "1.0.0",
        "formula": formula,
        "input_fact_ids": [],
        "input_calculation_ids": sorted(input_calculation_ids),
        "input_assumption_ids": sorted(input_assumption_ids),
        "output_name": output_name,
        "output_value": value,
        "unit": "USD" if output_name != "diluted_shares" else "shares",
        "contract_version": "3.0.0",
    }
    return build_hashed(CalculationLineage, **values)


def forecast_operating_case(
    statements: NormalizedFinancialStatements,
    scenario: str,
    drivers: list[ForecastDriver],
    *,
    terminal_growth: float,
    terminal_roic: float,
) -> tuple[OperatingForecast, tuple[CalculationLineage, ...]]:
    if scenario not in {"bear", "base", "bull"}:
        raise ForecastCalculationError("unknown scenario")
    by_year: dict[int, dict[str, ForecastDriver]] = defaultdict(dict)
    for driver in drivers:
        if driver.scenario != scenario:
            raise ForecastCalculationError("driver scenario does not match forecast case")
        if driver.name in by_year[driver.year]:
            raise ForecastCalculationError("duplicate forecast driver")
        by_year[driver.year][driver.name] = driver
    if len(by_year) < 2:
        raise ForecastCalculationError("at least two explicit forecast years are required")
    if any(set(items) != _REQUIRED_DRIVERS for items in by_year.values()):
        raise ForecastCalculationError("forecast driver set is incomplete")
    last: FinancialPeriod = statements.adjusted_periods[-1]
    revenue, shares = last.revenue, last.diluted_shares
    periods: list[ForecastPeriod] = []
    lineages: list[CalculationLineage] = []
    prior_output_ids = [item.calculation_id for item in statements.calculation_lineage]
    for year, items in sorted(by_year.items()):
        growth = items["revenue_growth"].value
        margin = items["operating_margin"].value
        tax_rate = items["tax_rate"].value
        reinvestment_rate = items["reinvestment_rate"].value
        dilution = items["share_dilution"].value
        exact_growth = Decimal(str(growth))
        exact_margin = Decimal(str(margin))
        exact_tax_rate = Decimal(str(tax_rate))
        exact_reinvestment_rate = Decimal(str(reinvestment_rate))
        exact_dilution = Decimal(str(dilution))
        if growth <= -1 or not -1 <= margin <= 1 or not 0 <= tax_rate <= 1:
            raise ForecastCalculationError("forecast assumptions exceed hard bounds")
        if not -2 <= reinvestment_rate <= 2 or dilution <= -1 or dilution > 1:
            raise ForecastCalculationError("reinvestment or dilution assumption is infeasible")
        revenue *= Decimal("1") + exact_growth
        operating_income = revenue * exact_margin
        nopat = operating_income * (Decimal("1") - exact_tax_rate)
        reinvestment = nopat * exact_reinvestment_rate
        fcff = nopat - reinvestment
        shares *= Decimal("1") + exact_dilution
        period = ForecastPeriod(
            year=year,
            revenue=revenue,
            operating_margin=margin,
            operating_income=operating_income,
            tax_rate=tax_rate,
            nopat=nopat,
            reinvestment=reinvestment,
            fcff=fcff,
            diluted_shares=shares,
        )
        periods.append(period)
        assumption_ids = [f"driver:{item.driver_id}" for item in items.values()]
        year_output_ids: list[str] = []
        for output_name, value, formula in (
            ("revenue", revenue, "prior_revenue * (1 + revenue_growth)"),
            ("operating_income", operating_income, "revenue * operating_margin"),
            ("nopat", nopat, "operating_income * (1 - tax_rate)"),
            ("reinvestment", reinvestment, "NOPAT * reinvestment_rate"),
            ("fcff", fcff, "NOPAT - reinvestment"),
            ("diluted_shares", shares, "prior_shares * (1 + share_dilution)"),
        ):
            lineages.append(
                _lineage(
                    scenario,
                    year,
                    output_name,
                    value,
                    formula,
                    prior_output_ids,
                    assumption_ids,
                )
            )
            year_output_ids.append(lineages[-1].calculation_id)
        prior_output_ids = year_output_ids
    values = {
        "forecast_id": f"operating-{statements.ticker}-{scenario}-{statements.as_of.date()}",
        "ticker": statements.ticker,
        "as_of": statements.as_of,
        "scenario": scenario,
        "periods": periods,
        "drivers": sorted(drivers, key=lambda item: (item.year, item.name, item.driver_id)),
        "terminal_growth": terminal_growth,
        "terminal_roic": terminal_roic,
        "calculation_ids": [item.calculation_id for item in lineages],
        "contract_version": "3.0.0",
    }
    return build_hashed(OperatingForecast, **values), tuple(lineages)


def validate_scenario_ordering(forecasts: dict[str, OperatingForecast]) -> None:
    if set(forecasts) != {"bear", "base", "bull"}:
        raise ForecastCalculationError("bear/base/bull forecasts are required")
    cases = [forecasts[name] for name in ("bear", "base", "bull")]
    if len({tuple(period.year for period in case.periods) for case in cases}) != 1:
        raise ForecastCalculationError("scenario years do not align")
    for bear, base, bull in zip(*(case.periods for case in cases), strict=True):
        if not bear.revenue <= base.revenue <= bull.revenue:
            raise ForecastCalculationError("scenario revenue ordering failed")
        if not bear.operating_margin <= base.operating_margin <= bull.operating_margin:
            raise ForecastCalculationError("scenario margin ordering failed")
        if not bear.fcff <= base.fcff <= bull.fcff:
            raise ForecastCalculationError("scenario FCFF ordering failed")
