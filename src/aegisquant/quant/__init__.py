"""Fixture-only deterministic quant primitives."""

from aegisquant.contracts.research import PerformanceReport
from aegisquant.quant.metrics import (
    performance_report,
    placebo_returns,
    stationary_block_bootstrap_indices,
    walk_forward_windows,
)
from aegisquant.quant.pit import (
    apply_available_corporate_actions,
    available_bars,
    marked_nav,
    next_market_bar,
)
from aegisquant.quant.portfolio import (
    Forecast,
    PortfolioPolicy,
    PortfolioTarget,
    blend_forecasts,
    build_long_only_target,
    propose_long_only,
)
from aegisquant.quant.timeline import ExecutionTimeline, TradableBar, next_tradable_bar

__all__ = [
    "ExecutionTimeline",
    "Forecast",
    "PerformanceReport",
    "PortfolioPolicy",
    "PortfolioTarget",
    "TradableBar",
    "apply_available_corporate_actions",
    "available_bars",
    "blend_forecasts",
    "build_long_only_target",
    "marked_nav",
    "next_market_bar",
    "next_tradable_bar",
    "performance_report",
    "placebo_returns",
    "propose_long_only",
    "stationary_block_bootstrap_indices",
    "walk_forward_windows",
]
