"""Deterministic company-archetype routing with explicit abstention."""

from __future__ import annotations

from aegis.contracts import CompanyArchetype
from aegis.contracts.fundamentals import ArchetypeKind

_FINANCIAL_SECTORS = {"Banks", "Financial Services", "Insurance"}
_REIT_SECTORS = {"REIT", "Real Estate Investment Trust"}
_CYCLICAL_SECTORS = {"Energy", "Materials", "Metals & Mining"}


def route_archetype(
    ticker: str,
    *,
    sector: str,
    subscription_revenue_share: float,
    profitable: bool,
) -> CompanyArchetype:
    if not 0 <= subscription_revenue_share <= 1:
        raise ValueError("subscription revenue share must be in [0, 1]")
    kind: ArchetypeKind
    if sector in _FINANCIAL_SECTORS:
        kind = "bank_financial"
        reason = "financial institutions require equity/capital and sector-specific valuation"
    elif sector in _REIT_SECTORS:
        kind = "reit"
        reason = "REIT analysis requires FFO/AFFO and property-specific valuation"
    elif sector in _CYCLICAL_SECTORS:
        kind = "cyclical_commodity"
        reason = "commodity/cyclical normalisation is not release-supported"
    elif not profitable:
        kind = "pre_profit"
        reason = "pre-profit valuation requires a dedicated path"
    elif subscription_revenue_share >= 0.7:
        kind = "saas_subscription"
        reason = "subscription unit-economics path is declared but not release-supported"
    else:
        kind = "general_operating_company"
        reason = "general non-financial operating-company path is supported"
    return CompanyArchetype(
        ticker=ticker,
        kind=kind,
        supported=kind == "general_operating_company",
        reason=reason,
        router_version="general-company-router-v1",
    )
