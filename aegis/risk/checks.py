"""Deterministic hard risk gate. Exposure removed by clamps remains cash."""

from __future__ import annotations

import math
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from aegis.contracts import PortfolioProposal, RiskDecision, RiskPolicy, canonical_sha256

_TOLERANCE = 1e-12


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
    names = sorted(set(target) | set(current))
    return 0.5 * sum(abs(target.get(name, 0.0) - current.get(name, 0.0)) for name in names)


def _finite_mapping(values: Mapping[str, float], label: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for name in sorted(values):
        value = values[name]
        try:
            finite = math.isfinite(value)
        except TypeError as exc:
            raise ValueError(f"{label} values must be finite numbers") from exc
        if not finite:
            raise ValueError(f"{label} values must be finite numbers")
        result[name] = value
    return result


def _append_violation(violations: list[str], message: str) -> None:
    if message not in violations:
        violations.append(message)


def _apply_safety_clamps(
    weights: dict[str, float],
    policy: RiskPolicy,
    sectors: Mapping[str, str],
    clamps: list[RiskClamp],
    violations: list[str],
) -> dict[str, float]:
    """Apply every exposure constraint; all operations only remove absolute exposure."""
    result = dict(sorted(weights.items()))

    if not policy.allow_shorting:
        for ticker in sorted(result):
            if result[ticker] < 0.0:
                clamps.append(
                    RiskClamp(rule="no_shorting", ticker=ticker, before=result[ticker], after=0.0)
                )
                result[ticker] = 0.0

    for ticker in sorted(result):
        before = result[ticker]
        if abs(before) > policy.max_position_pct:
            after = policy.max_position_pct if before > 0.0 else -policy.max_position_pct
            clamps.append(
                RiskClamp(rule="max_position_pct", ticker=ticker, before=before, after=after)
            )
            result[ticker] = after

    missing_sectors = sorted(set(result).difference(sectors))
    if missing_sectors:
        _append_violation(violations, f"missing sector classification: {missing_sectors}")
    else:
        sector_names = sorted({sectors[ticker] for ticker in result})
        for sector in sector_names:
            members = [ticker for ticker in sorted(result) if sectors[ticker] == sector]
            exposure = sum(max(result[ticker], 0.0) for ticker in members)
            if exposure > policy.maximum_sector_pct:
                scale = policy.maximum_sector_pct / exposure
                for ticker in members:
                    if result[ticker] > 0.0:
                        result[ticker] *= scale
                clamps.append(
                    RiskClamp(
                        rule="maximum_sector_pct",
                        group=sector,
                        before=exposure,
                        after=policy.maximum_sector_pct,
                    )
                )

    gross = sum(abs(result[ticker]) for ticker in sorted(result))
    net = abs(sum(result[ticker] for ticker in sorted(result)))
    gross_cap = min(policy.max_gross_exposure, 1.0 - policy.minimum_cash_pct)
    scale = min(
        1.0,
        gross_cap / gross if gross else 1.0,
        policy.max_net_exposure / net if net else 1.0,
    )
    if scale < 1.0:
        before_gross = gross
        for ticker in sorted(result):
            result[ticker] *= scale
        clamps.append(
            RiskClamp(
                rule="gross_net_and_cash",
                before=before_gross,
                after=sum(abs(result[ticker]) for ticker in sorted(result)),
            )
        )

    return result


def _record_safety_violations(
    weights: Mapping[str, float],
    policy: RiskPolicy,
    sectors: Mapping[str, str],
    violations: list[str],
) -> None:
    """Fail closed if any hard constraint remains after the last transformation."""
    if any(not math.isfinite(weight) for weight in weights.values()):
        _append_violation(violations, "non-finite position remains after risk clamps")
        return

    if not policy.allow_shorting and any(weight < -_TOLERANCE for weight in weights.values()):
        _append_violation(violations, "short position remains after risk clamps")
    if any(abs(weight) > policy.max_position_pct + _TOLERANCE for weight in weights.values()):
        _append_violation(violations, "position cap cannot be satisfied from current book")

    missing_sectors = sorted(set(weights).difference(sectors))
    if missing_sectors:
        _append_violation(violations, f"missing sector classification: {missing_sectors}")
    else:
        for sector in sorted({sectors[ticker] for ticker in weights}):
            sector_exposure = sum(
                max(weights[ticker], 0.0) for ticker in sorted(weights) if sectors[ticker] == sector
            )
            if sector_exposure > policy.maximum_sector_pct + _TOLERANCE:
                _append_violation(
                    violations,
                    f"sector {sector} exposure {sector_exposure:.6f} exceeds maximum",
                )

    gross = sum(abs(weights[ticker]) for ticker in sorted(weights))
    signed_net = sum(weights[ticker] for ticker in sorted(weights))
    net = abs(signed_net)
    if gross > policy.max_gross_exposure + _TOLERANCE:
        _append_violation(violations, "gross cap cannot be satisfied from current book")
    if net > policy.max_net_exposure + _TOLERANCE:
        _append_violation(violations, "net cap cannot be satisfied from current book")
    if not policy.allow_leverage and gross > 1.0 + _TOLERANCE:
        _append_violation(violations, "leverage would remain after risk clamps")
    if 1.0 - signed_net < policy.minimum_cash_pct - _TOLERANCE:
        _append_violation(violations, "minimum cash cannot be satisfied from current book")


def evaluate_risk(
    proposal: PortfolioProposal,
    policy: RiskPolicy,
    current_weights: Mapping[str, float] | None = None,
    sector_by_ticker: Mapping[str, str] | None = None,
    strategy_allocations: Mapping[str, float] | None = None,
) -> RiskEvaluation:
    """Clamp a proposed book using an immutable versioned policy and typed context."""
    current = _finite_mapping(current_weights or {}, "current_weights")
    sectors = {ticker.upper(): sector for ticker, sector in (sector_by_ticker or {}).items()}
    strategies = _finite_mapping(strategy_allocations or {}, "strategy_allocations")
    weights = dict(sorted(proposal.target_weights.items()))
    clamps: list[RiskClamp] = []
    warnings: list[str] = []
    violations: list[str] = []

    weights = _apply_safety_clamps(weights, policy, sectors, clamps, violations)
    safe_target = dict(weights)

    for strategy, allocation in strategies.items():
        if allocation > policy.maximum_single_strategy_pct + _TOLERANCE:
            _append_violation(
                violations,
                f"strategy {strategy} allocation {allocation:.6f} exceeds maximum",
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

        # A turnover limit may delay new risk, but may not undo an explicit
        # reduction in absolute exposure. Such reductions override turnover.
        for ticker in names:
            target_weight = safe_target.get(ticker, 0.0)
            if abs(target_weight) < abs(current.get(ticker, 0.0)):
                before = limited[ticker]
                if before != target_weight:
                    limited[ticker] = target_weight
                    clamps.append(
                        RiskClamp(
                            rule="de_risk_overrides_turnover",
                            ticker=ticker,
                            before=before,
                            after=target_weight,
                        )
                    )
        weights = limited

        # Interpolation toward an invalid current book can reintroduce any hard
        # breach, so run the complete safety gate again after turnover handling.
        weights = _apply_safety_clamps(weights, policy, sectors, clamps, violations)

    weights = {ticker: weight for ticker, weight in sorted(weights.items()) if abs(weight) > 1e-15}
    _record_safety_violations(weights, policy, sectors, violations)

    realized_turnover = _turnover(weights, current)
    if realized_turnover > policy.max_turnover_pct + _TOLERANCE:
        warnings.append(
            "turnover limit overridden to preserve de-risking and hard safety constraints"
        )

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
