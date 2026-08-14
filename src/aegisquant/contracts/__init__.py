"""Strict, versioned cross-service contracts."""

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
    OrderIntent,
    RiskDecisionPayload,
    SignedHumanApproval,
    SignedRiskDecision,
)

__all__ = [
    "CapabilityGrant",
    "CashLedgerEntry",
    "CorporateAction",
    "DataSnapshot",
    "EvidenceRecord",
    "HumanApprovalPayload",
    "InvestmentCase",
    "InvestmentCaseRequest",
    "Last30DaysResearchRecord",
    "LearningCandidate",
    "LearningEvaluation",
    "MarketBar",
    "NumericClaim",
    "OrderBundle",
    "OrderIntent",
    "PaperFill",
    "PerformanceReport",
    "PositionLedgerEntry",
    "PromotionApproval",
    "ResearchManifest",
    "RightsManifest",
    "RiskDecisionPayload",
    "SecurityVersion",
    "SignedHumanApproval",
    "SignedRiskDecision",
    "SourceReceipt",
    "ToolAuthorizationRequest",
    "TrialManifest",
]
