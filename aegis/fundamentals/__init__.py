"""Institutional fundamental-intelligence engine."""

from .archetypes import route_archetype
from .fixtures import load_fundamental_fixture
from .forecasting import forecast_operating_case, validate_scenario_ordering
from .graph import FixtureFundamentalProvider, run_fundamental_graph
from .management import evaluate_management
from .metrics import calculate_metrics
from .normalization import normalize_statements, raw_snapshot, reverse_adjustments
from .service import FundamentalResearchInputs
from .thesis import ThesisLedger, build_thesis
from .valuation import (
    calculate_comparables,
    calculate_dcf,
    combine_scenarios,
    solve_implied_assumption,
    solve_implied_growth,
)

__all__ = [
    "FixtureFundamentalProvider",
    "FundamentalResearchInputs",
    "ThesisLedger",
    "build_thesis",
    "calculate_comparables",
    "calculate_dcf",
    "calculate_metrics",
    "combine_scenarios",
    "evaluate_management",
    "forecast_operating_case",
    "load_fundamental_fixture",
    "normalize_statements",
    "raw_snapshot",
    "reverse_adjustments",
    "route_archetype",
    "run_fundamental_graph",
    "solve_implied_assumption",
    "solve_implied_growth",
    "validate_scenario_ordering",
]
