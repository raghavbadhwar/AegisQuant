"""Validated semantic calculation-ID selectors for fundamental outputs."""

from __future__ import annotations

from typing import Literal

from aegis.contracts import ComparableValuation, DCFResult, ImpliedExpectations, ScenarioValuation


class CalculationIdentityError(ValueError):
    pass


def _require_exact_id(calculation_ids: list[str], expected: str) -> str:
    if calculation_ids.count(expected) != 1:
        raise CalculationIdentityError(f"expected exactly one indexed calculation: {expected}")
    return expected


def dcf_calculation_id(result: DCFResult, output: str) -> str:
    return _require_exact_id(
        result.calculation_ids,
        f"dcf-v1:{result.forecast_id}:{output}",
    )


def scenario_calculation_id(
    result: ScenarioValuation,
    output: Literal["probability_weighted_value", "implied_return"],
) -> str:
    suffix = output.replace("_", "-")
    return _require_exact_id(result.calculation_ids, f"scenario-valuation-v1:{suffix}")


def reverse_dcf_calculation_id(result: ImpliedExpectations) -> str:
    variable = result.solved_variable.replace("_", "-")
    suffix = "" if result.feasible else ":no-root"
    return _require_exact_id(
        result.calculation_ids,
        f"reverse-dcf-bisection-v1:{variable}{suffix}",
    )


def comparable_calculation_id(
    result: ComparableValuation,
    output: str,
) -> str:
    if output not in {"low", "mid", "high"}:
        raise CalculationIdentityError(f"unknown comparable output: {output}")
    return _require_exact_id(
        result.calculation_ids,
        f"comparable-valuation-v2:implied-{output}",
    )
