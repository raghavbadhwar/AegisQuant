"""Deterministic management guidance and capital-allocation tracking."""

from __future__ import annotations

from aegis.contracts import (
    GuidanceRecord,
    ManagementActionRecord,
    ManagementTrackRecord,
    NormalizedFinancialStatements,
)


def evaluate_management(
    statements: NormalizedFinancialStatements,
    guidance: list[GuidanceRecord],
    actions: list[ManagementActionRecord],
) -> ManagementTrackRecord:
    eligible = [record for record in guidance if record.issued_at <= statements.as_of]
    matured = [
        record
        for record in eligible
        if record.actual is not None and record.actual_available_at <= statements.as_of  # type: ignore[operator]
    ]
    hits = [
        record
        for record in matured
        if record.actual is not None and record.lower_bound <= record.actual <= record.upper_bound
    ]
    biases = [
        record.actual - (record.lower_bound + record.upper_bound) / 2
        for record in matured
        if record.actual is not None
    ]
    errors = [abs(value) for value in biases]
    current, prior = statements.adjusted_periods[-1], statements.adjusted_periods[-2]
    dilution = float(current.diluted_shares / prior.diluted_shares - 1)
    eligible_actions = [action for action in actions if action.available_at <= statements.as_of]
    known_completed = {
        action.action_id
        for action in eligible_actions
        if action.completed
        and action.completion_available_at is not None
        and action.completion_available_at <= statements.as_of
    }
    promises = [a for a in eligible_actions if a.action_type == "capital_allocation_promise"]
    acquisitions = [
        a.outcome_return
        for a in eligible_actions
        if a.action_type == "acquisition"
        and a.outcome_return is not None
        and a.outcome_available_at is not None
        and a.outcome_available_at <= statements.as_of
    ]
    buybacks = [
        a.outcome_return
        for a in eligible_actions
        if a.action_type == "buyback"
        and a.outcome_return is not None
        and a.outcome_available_at is not None
        and a.outcome_available_at <= statements.as_of
    ]
    evidence_ids = sorted(
        {evidence_id for record in eligible for evidence_id in record.evidence_ids}
        | {evidence_id for action in eligible_actions for evidence_id in action.evidence_ids}
    )
    calculation_ids = ["management-track-v1:dilution", "management-track-v1:disclosure-quality"]
    if matured:
        calculation_ids.extend(
            [
                "management-track-v1:guidance-hit-rate",
                "management-track-v1:guidance-bias",
                "management-track-v1:guidance-mae",
            ]
        )
    calculation_ids.append("management-track-v1:guidance-revision-count")
    if acquisitions:
        calculation_ids.append("management-track-v1:acquisition-return")
    if buybacks:
        calculation_ids.append("management-track-v1:buyback-timing-return")
    if promises:
        calculation_ids.append("management-track-v1:capital-allocation-follow-through")
    return ManagementTrackRecord(
        ticker=statements.ticker,
        as_of=statements.as_of,
        guidance=sorted(eligible, key=lambda item: (item.issued_at, item.guidance_id)),
        matured_count=len(matured),
        hit_rate=len(hits) / len(matured) if matured else None,
        mean_bias=sum(biases) / len(biases) if biases else None,
        mean_absolute_error=sum(errors) / len(errors) if errors else None,
        dilution_rate=dilution,
        acquisition_return=sum(acquisitions) / len(acquisitions) if acquisitions else None,
        buyback_timing_return=sum(buybacks) / len(buybacks) if buybacks else None,
        capital_allocation_follow_through=(
            sum(a.action_id in known_completed for a in promises) / len(promises)
            if promises
            else None
        ),
        guidance_revision_count=sum(item.supersedes_guidance_id is not None for item in eligible),
        disclosure_quality=len(matured) / len(eligible) if eligible else 0.5,
        evidence_ids=evidence_ids,
        calculation_ids=calculation_ids,
    )
