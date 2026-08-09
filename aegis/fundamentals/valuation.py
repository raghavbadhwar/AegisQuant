"""Deterministic FCFF, reverse-DCF, comparable and scenario valuation."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from statistics import median
from typing import Literal

from aegis.contracts import (
    CalculationLineage,
    ComparableValuation,
    DCFResult,
    ImpliedExpectations,
    OperatingForecast,
    PeerMultiple,
    ScenarioValuation,
    SensitivityPoint,
    ValuationAssumption,
)

from .hashing import build_hashed


class ValuationError(RuntimeError):
    pass


def _d(value: Decimal | float | int) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _enterprise_value(
    forecast: OperatingForecast, discount_rate: float, terminal_growth: float
) -> tuple[Decimal, Decimal, Decimal]:
    if not 0 < discount_rate < 1 or not -1 < terminal_growth < discount_rate:
        raise ValuationError("discount and terminal-growth assumptions are infeasible")
    rate = _d(discount_rate)
    growth = _d(terminal_growth)
    one = Decimal("1")
    explicit = sum(
        (
            _d(period.fcff) / (one + rate) ** index
            for index, period in enumerate(forecast.periods, start=1)
        ),
        Decimal("0"),
    )
    terminal_roic = _d(forecast.terminal_roic)
    if growth > 0 and terminal_roic <= growth:
        raise ValuationError("terminal ROIC must exceed positive terminal growth")
    terminal_reinvestment_rate = growth / terminal_roic
    terminal_fcff = (
        _d(forecast.periods[-1].nopat) * (one + growth) * (one - terminal_reinvestment_rate)
    )
    terminal = terminal_fcff / (rate - growth)
    terminal_pv = terminal / (one + rate) ** len(forecast.periods)
    return explicit, terminal, terminal_pv


def _lineage(
    forecast: OperatingForecast,
    name: str,
    value: Decimal,
    formula: str,
) -> CalculationLineage:
    values = {
        "calculation_id": f"dcf-v1:{forecast.forecast_id}:{name}",
        "calculator": "fcff-dcf",
        "calculator_version": "1.0.0",
        "formula": formula,
        "input_fact_ids": [],
        "input_calculation_ids": forecast.calculation_ids,
        "input_assumption_ids": [
            f"{forecast.forecast_id}:discount-rate",
            f"{forecast.forecast_id}:terminal-growth",
            f"{forecast.forecast_id}:net-debt",
            f"{forecast.forecast_id}:terminal-roic",
            f"{forecast.forecast_id}:diluted-shares",
        ],
        "output_name": name,
        "output_value": value,
        "unit": "USD",
        "contract_version": "3.0.0",
    }
    return build_hashed(CalculationLineage, **values)


def calculate_dcf(
    forecast: OperatingForecast,
    *,
    discount_rate: float,
    terminal_growth: float,
    net_debt: Decimal,
    diluted_shares: Decimal | None = None,
    evidence_ids: list[str],
) -> tuple[DCFResult, tuple[CalculationLineage, ...]]:
    shares = _d(forecast.periods[-1].diluted_shares) if diluted_shares is None else diluted_shares
    if shares <= 0:
        raise ValuationError("diluted shares must be positive")
    explicit, terminal, terminal_pv = _enterprise_value(forecast, discount_rate, terminal_growth)
    enterprise = explicit + terminal_pv
    equity = enterprise - net_debt
    per_share = equity / shares
    lineages = (
        _lineage(forecast, "explicit_present_value", explicit, "sum(FCFF_t/(1+WACC)^t)"),
        _lineage(
            forecast,
            "terminal_value",
            terminal,
            "NOPAT_n*(1+g)*(1-g/terminal_ROIC)/(WACC-g)",
        ),
        _lineage(
            forecast,
            "terminal_present_value",
            terminal_pv,
            "terminal_value/(1+WACC)^n",
        ),
        _lineage(
            forecast,
            "enterprise_value",
            enterprise,
            "explicit_present_value + terminal_present_value",
        ),
        _lineage(forecast, "equity_value", equity, "enterprise_value - net_debt"),
        _lineage(forecast, "value_per_share", per_share, "equity_value / diluted_shares"),
    )
    assumptions = [
        ValuationAssumption(
            assumption_id=f"{forecast.forecast_id}:discount-rate",
            name="discount_rate",
            value=_d(discount_rate),
            unit="ratio",
            scenario=forecast.scenario,
            evidence_ids=evidence_ids,
        ),
        ValuationAssumption(
            assumption_id=f"{forecast.forecast_id}:terminal-growth",
            name="terminal_growth",
            value=_d(terminal_growth),
            unit="ratio",
            scenario=forecast.scenario,
            evidence_ids=evidence_ids,
        ),
        ValuationAssumption(
            assumption_id=f"{forecast.forecast_id}:net-debt",
            name="net_debt",
            value=net_debt,
            unit="USD",
            scenario=forecast.scenario,
            evidence_ids=evidence_ids,
        ),
        ValuationAssumption(
            assumption_id=f"{forecast.forecast_id}:terminal-roic",
            name="terminal_roic",
            value=_d(forecast.terminal_roic),
            unit="ratio",
            scenario=forecast.scenario,
            evidence_ids=evidence_ids,
        ),
        ValuationAssumption(
            assumption_id=f"{forecast.forecast_id}:diluted-shares",
            name="diluted_shares",
            value=shares,
            unit="shares",
            scenario=forecast.scenario,
            calculation_ids=[
                calculation_id
                for calculation_id in forecast.calculation_ids
                if calculation_id.endswith(":diluted_shares")
            ],
        ),
    ]
    sensitivity = []
    sensitivity_lineage: list[CalculationLineage] = []
    rate_shifts = (Decimal("-0.01"), Decimal("0"), Decimal("0.01"))
    growth_shifts = (Decimal("-0.005"), Decimal("0"), Decimal("0.005"))
    for rate_shift in rate_shifts:
        for growth_shift in growth_shifts:
            rate_decimal = _d(discount_rate) + rate_shift
            growth_decimal = _d(terminal_growth) + growth_shift
            if rate_decimal <= 0 or growth_decimal >= rate_decimal:
                continue
            rate = float(rate_decimal)
            growth = float(growth_decimal)
            rate_token = format(rate_decimal.normalize(), "f")
            growth_token = format(growth_decimal.normalize(), "f")
            coordinate = f"wacc={rate_token}:g={growth_token}"
            rate_calculation_id = (
                f"dcf-sensitivity-v1:{forecast.forecast_id}:{coordinate}:discount_rate"
            )
            growth_calculation_id = (
                f"dcf-sensitivity-v1:{forecast.forecast_id}:{coordinate}:terminal_growth"
            )
            enterprise_calculation_id = (
                f"dcf-sensitivity-v1:{forecast.forecast_id}:{coordinate}:enterprise_value"
            )
            per_share_calculation_id = (
                f"dcf-sensitivity-v1:{forecast.forecast_id}:{coordinate}:equity_value_per_share"
            )
            sens_explicit, _, sens_terminal_pv = _enterprise_value(forecast, rate, growth)
            sens_enterprise = sens_explicit + sens_terminal_pv
            sens_per_share = (sens_enterprise - net_debt) / shares
            sensitivity_lineage.extend(
                [
                    build_hashed(
                        CalculationLineage,
                        calculation_id=rate_calculation_id,
                        calculator="fcff-dcf-sensitivity-grid",
                        calculator_version="1.0.0",
                        formula=f"base_discount_rate + ({rate_shift})",
                        input_fact_ids=[],
                        input_calculation_ids=[],
                        input_assumption_ids=[f"{forecast.forecast_id}:discount-rate"],
                        output_name=f"{coordinate}_discount_rate",
                        output_value=rate_decimal,
                        unit="ratio",
                        contract_version="3.0.0",
                    ),
                    build_hashed(
                        CalculationLineage,
                        calculation_id=growth_calculation_id,
                        calculator="fcff-dcf-sensitivity-grid",
                        calculator_version="1.0.0",
                        formula=f"base_terminal_growth + ({growth_shift})",
                        input_fact_ids=[],
                        input_calculation_ids=[],
                        input_assumption_ids=[f"{forecast.forecast_id}:terminal-growth"],
                        output_name=f"{coordinate}_terminal_growth",
                        output_value=growth_decimal,
                        unit="ratio",
                        contract_version="3.0.0",
                    ),
                    build_hashed(
                        CalculationLineage,
                        calculation_id=enterprise_calculation_id,
                        calculator="fcff-dcf-sensitivity",
                        calculator_version="1.0.0",
                        formula=(
                            "sum(FCFF_t/(1+WACC_s)^t) + terminal_FCFF_s/(WACC_s-g_s)/(1+WACC_s)^n"
                        ),
                        input_fact_ids=[],
                        input_calculation_ids=[
                            *forecast.calculation_ids,
                            rate_calculation_id,
                            growth_calculation_id,
                        ],
                        input_assumption_ids=[f"{forecast.forecast_id}:terminal-roic"],
                        output_name=f"{coordinate}_enterprise_value",
                        output_value=sens_enterprise,
                        unit="USD",
                        contract_version="3.0.0",
                    ),
                    build_hashed(
                        CalculationLineage,
                        calculation_id=per_share_calculation_id,
                        calculator="fcff-dcf-sensitivity",
                        calculator_version="1.0.0",
                        formula="(sensitivity_enterprise_value - net_debt) / diluted_shares",
                        input_fact_ids=[],
                        input_calculation_ids=[enterprise_calculation_id],
                        input_assumption_ids=[
                            f"{forecast.forecast_id}:net-debt",
                            f"{forecast.forecast_id}:diluted-shares",
                        ],
                        output_name=f"{coordinate}_equity_value_per_share",
                        output_value=sens_per_share,
                        unit="USD/share",
                        contract_version="3.0.0",
                    ),
                ]
            )
            sensitivity.append(
                SensitivityPoint(
                    discount_rate=rate,
                    terminal_growth=growth,
                    enterprise_value=sens_enterprise,
                    equity_value_per_share=sens_per_share,
                    discount_rate_calculation_id=rate_calculation_id,
                    terminal_growth_calculation_id=growth_calculation_id,
                    enterprise_value_calculation_id=enterprise_calculation_id,
                    equity_value_per_share_calculation_id=per_share_calculation_id,
                )
            )
    all_lineages = (*lineages, *sensitivity_lineage)

    values = {
        "valuation_id": f"dcf-{forecast.forecast_id}",
        "ticker": forecast.ticker,
        "scenario": forecast.scenario,
        "as_of": forecast.as_of,
        "forecast_id": forecast.forecast_id,
        "discount_rate": discount_rate,
        "terminal_growth": terminal_growth,
        "explicit_present_value": explicit,
        "terminal_value": terminal,
        "terminal_present_value": terminal_pv,
        "enterprise_value": enterprise,
        "net_debt": net_debt,
        "diluted_shares": shares,
        "equity_value": equity,
        "value_per_share": per_share,
        "sensitivity": sorted(
            sensitivity, key=lambda item: (item.discount_rate, item.terminal_growth)
        ),
        "assumptions": assumptions,
        "calculation_ids": [item.calculation_id for item in all_lineages],
        "contract_version": "3.0.0",
    }
    return build_hashed(DCFResult, **values), all_lineages


def solve_implied_assumption(
    *,
    ticker: str,
    market_price: Decimal | float | int,
    valuation_for_assumption: Callable[[float], Decimal | float],
    solved_variable: Literal["revenue_growth", "growth_duration", "operating_margin"],
    lower_bound: float,
    upper_bound: float,
    assumption_ids: list[str],
    tolerance: Decimal = Decimal("1e-8"),
    max_iterations: int = 200,
) -> ImpliedExpectations:
    price = _d(market_price)
    if price <= 0 or lower_bound >= upper_bound:
        raise ValuationError("reverse-DCF price or bounds are invalid")
    if solved_variable not in {"revenue_growth", "growth_duration", "operating_margin"}:
        raise ValuationError("unknown reverse-DCF solved variable")
    low_value = _d(valuation_for_assumption(lower_bound)) - price
    high_value = _d(valuation_for_assumption(upper_bound)) - price
    limitations = ["one-variable inversion holds other operating and valuation assumptions fixed"]
    if low_value == 0:
        implied, residual = lower_bound, Decimal("0")
    elif high_value == 0:
        implied, residual = upper_bound, Decimal("0")
    elif low_value * high_value > 0:
        return ImpliedExpectations(
            expectations_id=f"reverse-dcf-{ticker}-{solved_variable}",
            ticker=ticker,
            market_price=price,
            solved_variable=solved_variable,
            implied_value=None,
            feasible=False,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            residual=None,
            limitations=[
                *limitations,
                "target price is outside the values spanned by supplied bounds",
            ],
            assumption_ids=assumption_ids,
            calculation_ids=[
                f"reverse-dcf-bisection-v1:{solved_variable.replace('_', '-')}:no-root"
            ],
        )
    else:
        low, high = lower_bound, upper_bound
        implied = (low + high) / 2
        residual = _d(valuation_for_assumption(implied)) - price
        for _ in range(max_iterations):
            implied = (low + high) / 2
            residual = _d(valuation_for_assumption(implied)) - price
            if abs(residual) <= tolerance:
                break
            if low_value * residual <= 0:
                high = implied
            else:
                low, low_value = implied, residual
        else:
            limitations.append("solver reached maximum iterations")
    return ImpliedExpectations(
        expectations_id=f"reverse-dcf-{ticker}-{solved_variable}",
        ticker=ticker,
        market_price=price,
        solved_variable=solved_variable,
        implied_value=implied,
        feasible=True,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        residual=residual,
        limitations=limitations,
        assumption_ids=assumption_ids,
        calculation_ids=[f"reverse-dcf-bisection-v1:{solved_variable.replace('_', '-')}"],
    )


def solve_implied_growth(
    *,
    ticker: str,
    market_price: Decimal | float | int,
    valuation_for_growth: Callable[[float], Decimal | float],
    lower_bound: float,
    upper_bound: float,
    assumption_ids: list[str],
    tolerance: Decimal = Decimal("1e-8"),
    max_iterations: int = 200,
) -> ImpliedExpectations:
    return solve_implied_assumption(
        ticker=ticker,
        market_price=market_price,
        valuation_for_assumption=valuation_for_growth,
        solved_variable="revenue_growth",
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        assumption_ids=assumption_ids,
        tolerance=tolerance,
        max_iterations=max_iterations,
    )


def calculate_comparables(
    *,
    ticker: str,
    peers: list[PeerMultiple],
    selection_rationale: str,
    target_revenue: Decimal,
    target_ebitda: Decimal,
    target_ebit: Decimal,
    target_net_income: Decimal,
    target_fcf: Decimal,
    target_net_debt: Decimal,
    target_shares: Decimal,
) -> ComparableValuation:
    targets = {
        "ev_revenue": (target_revenue, True),
        "ev_ebitda": (target_ebitda, True),
        "ev_ebit": (target_ebit, True),
        "price_earnings": (target_net_income, False),
        "price_fcf": (target_fcf, False),
    }
    if target_shares <= 0:
        raise ValuationError("positive target shares are required")
    distributions: dict[str, list[float]] = {}
    method_ranges: list[tuple[Decimal, Decimal, Decimal]] = []
    for name, (target, enterprise_multiple) in targets.items():
        multiples = sorted(value for peer in peers if (value := getattr(peer, name)) is not None)
        if len(multiples) < 2:
            continue
        distributions[name] = multiples
        decimal_multiples = [_d(value) for value in multiples]
        low, mid, high = (
            decimal_multiples[0],
            median(decimal_multiples),
            decimal_multiples[-1],
        )

        implied_values = []
        for multiple in (low, mid, high):
            aggregate = multiple * target
            equity = aggregate - target_net_debt if enterprise_multiple else aggregate
            implied_values.append(equity / target_shares)
        method_ranges.append((implied_values[0], implied_values[1], implied_values[2]))
    if not method_ranges:
        raise ValuationError("at least one comparable method requires two valid peers")
    low_value = min(values[0] for values in method_ranges)
    mid_value = median(values[1] for values in method_ranges)
    high_value = max(values[2] for values in method_ranges)
    return ComparableValuation(
        valuation_id=f"comps-{ticker}-multi-method",
        ticker=ticker,
        peers=sorted(peers, key=lambda item: item.ticker),
        selection_rationale=selection_rationale,
        multiple_distributions=distributions,
        implied_value_low=low_value,
        implied_value_mid=mid_value,
        implied_value_high=high_value,
        calculation_ids=[
            "comparable-valuation-v2:implied-low",
            "comparable-valuation-v2:implied-mid",
            "comparable-valuation-v2:implied-high",
        ],
        limitations=["peer distributions contextualise rather than establish precise fair value"],
    )


def combine_scenarios(
    *,
    ticker: str,
    dcf_by_scenario: dict[str, DCFResult],
    probabilities: dict[str, float],
    market_price: Decimal,
) -> ScenarioValuation:
    required = ("bear", "base", "bull")
    if set(dcf_by_scenario) != set(required) or set(probabilities) != set(required):
        raise ValuationError("bear/base/bull valuation cases are required")
    weighted = sum(
        (_d(probabilities[name]) * dcf_by_scenario[name].value_per_share for name in required),
        Decimal("0"),
    )
    return ScenarioValuation(
        ticker=ticker,
        dcf_by_scenario=dcf_by_scenario,  # type: ignore[arg-type]
        probabilities=probabilities,  # type: ignore[arg-type]
        probability_weighted_value=weighted,
        market_price=market_price,
        implied_return=float(weighted / market_price - Decimal("1")),
        calculation_ids=[
            "scenario-valuation-v1:probability-weighted-value",
            "scenario-valuation-v1:implied-return",
        ],
    )
