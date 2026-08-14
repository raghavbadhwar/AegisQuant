#!/usr/bin/env python3
"""Export or verify the versioned JSON Schema contract fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from aegisquant.contracts.artifact import ArtifactEnvelope, ValidationReceipt
from aegisquant.contracts.capability import CapabilityGrant, ToolAuthorizationRequest
from aegisquant.contracts.case import InvestmentCase, InvestmentCaseRequest
from aegisquant.contracts.evidence import EvidenceRecord, NumericClaim, RightsManifest
from aegisquant.contracts.learning import LearningCandidate, LearningEvaluation, PromotionApproval
from aegisquant.contracts.research import (
    CashLedgerEntry,
    CorporateAction,
    DataSnapshot,
    Last30DaysResearchRecord,
    MarketBar,
    PaperFill,
    PerformanceReport,
    PositionLedgerEntry,
    ResearchManifest,
    SecurityVersion,
    SourceReceipt,
    TrialManifest,
)
from aegisquant.contracts.risk import (
    HumanApprovalPayload,
    OrderBundle,
    RiskDecisionPayload,
    SignedHumanApproval,
    SignedRiskDecision,
)
from aegisquant.fixture_case import FixtureCaseReport, FixtureCaseSpec
from aegisquant.intelligence.forecast_evidence import ForecastAssessment, ForecastEvidenceBundle
from aegisquant.quant.multi_period import MultiPeriodCaseReport, MultiPeriodCaseSpec

SCHEMAS: dict[str, Any] = {
    "artifact-envelope-v1": ArtifactEnvelope,
    "capability-grant-v1": CapabilityGrant,
    "cash-ledger-entry-v1": CashLedgerEntry,
    "corporate-action-v1": CorporateAction,
    "data-snapshot-v1": DataSnapshot,
    "evidence-record-v1": EvidenceRecord,
    "fixture-case-report-v1": FixtureCaseReport,
    "fixture-case-spec-v1": FixtureCaseSpec,
    "forecast-assessment-v1": ForecastAssessment,
    "forecast-evidence-bundle-v1": ForecastEvidenceBundle,
    "human-approval-payload-v1": HumanApprovalPayload,
    "investment-case-request-v1": InvestmentCaseRequest,
    "investment-case-v1": InvestmentCase,
    "learning-candidate-v1": LearningCandidate,
    "learning-evaluation-v1": LearningEvaluation,
    "last30days-research-record-v1": Last30DaysResearchRecord,
    "market-bar-v1": MarketBar,
    "multi-period-case-report-v1": MultiPeriodCaseReport,
    "multi-period-case-spec-v1": MultiPeriodCaseSpec,
    "numeric-claim-v1": NumericClaim,
    "order-bundle-v1": OrderBundle,
    "paper-fill-v1": PaperFill,
    "performance-report-v1": PerformanceReport,
    "position-ledger-entry-v1": PositionLedgerEntry,
    "promotion-approval-v1": PromotionApproval,
    "research-manifest-v1": ResearchManifest,
    "rights-manifest-v1": RightsManifest,
    "risk-decision-payload-v1": RiskDecisionPayload,
    "security-version-v1": SecurityVersion,
    "source-receipt-v1": SourceReceipt,
    "signed-risk-decision-v1": SignedRiskDecision,
    "signed-human-approval-v1": SignedHumanApproval,
    "tool-authorization-request-v1": ToolAuthorizationRequest,
    "trial-manifest-v1": TrialManifest,
    "validation-receipt-v1": ValidationReceipt,
}
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "schemas"


def rendered_schema(model: Any) -> bytes:
    return (
        json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    for name, model in SCHEMAS.items():
        path = OUTPUT / f"{name}.json"
        expected = rendered_schema(model)
        if arguments.check:
            if not path.exists() or path.read_bytes() != expected:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_bytes(expected)
    if stale:
        print("stale contract schemas:")
        print("\n".join(f"- {item}" for item in stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
