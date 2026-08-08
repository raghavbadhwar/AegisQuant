"""Hash-bound research-lab contract builders."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel

from aegis.contracts import (
    ExperimentRecord,
    PostmortemReport,
    PromotionDecision,
    ValidationReport,
    canonical_sha256,
)


def _build(contract: type[BaseModel], values: dict[str, Any]) -> BaseModel:
    draft = contract.model_construct(**values, content_hash="0" * 64)
    payload = draft.model_dump(exclude={"content_hash"})
    return contract(**values, content_hash=canonical_sha256(payload))


def build_experiment(**values: Any) -> ExperimentRecord:
    return cast(ExperimentRecord, _build(ExperimentRecord, values))


def build_validation_report(**values: Any) -> ValidationReport:
    return cast(ValidationReport, _build(ValidationReport, values))


def build_promotion_decision(**values: Any) -> PromotionDecision:
    return cast(PromotionDecision, _build(PromotionDecision, values))


def build_postmortem(**values: Any) -> PostmortemReport:
    return cast(PostmortemReport, _build(PostmortemReport, values))
