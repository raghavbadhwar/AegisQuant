"""Deterministic hard risk gate. Exposure removed by clamps remains cash."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from aegis.contracts import PortfolioProposal, RiskDecision, RiskPolicy, canonical_sha256


class RiskClamp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: str
    ticker: str | None = None
    group: str | None = None
    before: float
    after: float


class RiskEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: RiskDecision
    clamps: tuple[RiskClamp, ...] = ()


def _turnover(target: Mapping[str, float], current: Mapping[str, float]) -> float:
    return 0.5 * sum(
        abs(target.get(name, 0.0) - current.get(name, 0.0)) for name in set(target) | set(current)
    )


def evaluate_risk(
    proposal: PortfolioProposal,
    policy: RiskPolicy,
    current_weights: Mapping[str, float] | None = None,
    sector_by_ticker: Mapping[str, str] | None = None,
    strategy_allocations: Mapping[str, float] | None = None,
) -> RiskEvaluation:
    """Clamp a proposed book using an immutable versioned policy and typed context."""
    current = dict(sorted((current_weights or {}).items()))
    sectors = {ticker.upper(): sector for ticker, sector in (sector_by_ticker or {}).items()}
    strategies = dict(sorted((strategy_allocations or {}).items()))
    weights = dict(sorted(proposal.target_weights.items()))
    clamps: list[RiskClamp] = []
    warnings: list[str] = []
    violations: list[str] = []

    if not policy.allow_shorting:
        for ticker in sorted(weights):
            if weights[ticker] < 0:
                clamps.append(
                    RiskClamp(rule="no_shorting", ticker=ticker, before=weights[ticker], after=0.0)
                )
                weights[ticker] = 0.0

    for ticker in sorted(weights):
        before = weights[ticker]
        if abs(before) > policy.max_position_pct:
            after = policy.max_position_pct if before > 0 else -policy.max_position_pct
            clamps.append(
                RiskClamp(rule="max_position_pct", ticker=ticker, before=before, after=after)
            )
            weights[ticker] = after

    missing_sectors = sorted(set(weights).difference(sectors))
    if missing_sectors:
        violations.append(f"missing sector classification: {missing_sectors}")
    else:
        sector_names = sorted(set(sectors[ticker] for ticker in weights))
        for sector in sector_names:
            members = [ticker for ticker in sorted(weights) if sectors[ticker] == sector]
            exposure = sum(max(weights[ticker], 0.0) for ticker in members)
            if exposure > policy.maximum_sector_pct:
                scale = policy.maximum_sector_pct / exposure
                for ticker in members:
                    if weights[ticker] > 0:
                        weights[ticker] *= scale
                clamps.append(
                    RiskClamp(
                        rule="maximum_sector_pct",
                        group=sector,
                        before=exposure,
                        after=policy.maximum_sector_pct,
                    )
                )

    for strategy, allocation in strategies.items():
        if allocation > policy.maximum_single_strategy_pct + 1e-12:
            violations.append(f"strategy {strategy} allocation {allocation:.6f} exceeds maximum")

    gross = sum(abs(weight) for weight in weights.values())
    net = abs(sum(weights.values()))
    gross_cap = min(policy.max_gross_exposure, 1.0 - policy.minimum_cash_pct)
    scale = min(
        1.0,
        gross_cap / gross if gross else 1.0,
        policy.max_net_exposure / net if net else 1.0,
    )
    if scale < 1.0:
        before_gross = gross
        for ticker in sorted(weights):
            weights[ticker] *= scale
        clamps.append(
            RiskClamp(
                rule="gross_net_and_cash",
                before=before_gross,
                after=sum(abs(weight) for weight in weights.values()),
            )
        )

    turnover = _turnover(weights, current)
    if turnover > policy.max_turnover_pct:
        turnover_scale = policy.max_turnover_pct / turnover
        names = sorted(set(weights) | set(current))
        limited = {
            ticker: current.get(ticker, 0.0)
            + turnover_scale * (weights.get(ticker, 0.0) - current.get(ticker, 0.0))
            for ticker in names
        }
        clamps.append(
            RiskClamp(
                rule="max_turnover_pct",
                before=turnover,
                after=policy.max_turnover_pct,
            )
        )
        weights = limited

    weights = {ticker: weight for ticker, weight in sorted(weights.items()) if abs(weight) > 1e-15}
    gross = sum(abs(weight) for weight in weights.values())
    net = abs(sum(weights.values()))
    if not policy.allow_shorting and any(weight < -1e-12 for weight in weights.values()):
        violations.append("short position remains after risk clamps")
    if any(abs(weight) > policy.max_position_pct + 1e-12 for weight in weights.values()):
        violations.append("position cap cannot be satisfied from current book")
    if gross > policy.max_gross_exposure + 1e-12:
        violations.append("gross cap cannot be satisfied from current book")
    if net > policy.max_net_exposure + 1e-12:
        violations.append("net cap cannot be satisfied from current book")
    if not policy.allow_leverage and gross > 1.0 + 1e-12:
        violations.append("leverage would remain after risk clamps")
    if 1.0 - sum(weights.values()) < policy.minimum_cash_pct - 1e-12:
        violations.append("minimum cash cannot be satisfied from current book")
    realized_turnover = _turnover(weights, current)
    if realized_turnover > policy.max_turnover_pct + 1e-12:
        warnings.append("turnover exceeded only to de-risk an already-invalid current book")

    input_hash = canonical_sha256(
        {
            "proposal": proposal.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"),
            "current_weights": current,
            "sector_by_ticker": sectors,
            "strategy_allocations": strategies,
        }
    )
    decision = RiskDecision(
        approved=not violations,
        final_weights=weights,
        violations=violations,
        warnings=warnings,
        policy_version=policy.version,
        input_hash=input_hash,
    )
    return RiskEvaluation(decision=decision, clamps=tuple(clamps))
