"""Strict, versioned cross-service contracts."""

from aegisquant.contracts.capability import CapabilityGrant, ToolAuthorizationRequest
from aegisquant.contracts.case import InvestmentCase, InvestmentCaseRequest
from aegisquant.contracts.evidence import EvidenceRecord, NumericClaim, RightsManifest
from aegisquant.contracts.risk import (
    OrderBundle,
    OrderIntent,
    RiskDecisionPayload,
    SignedRiskDecision,
)

__all__ = [
    "CapabilityGrant",
    "EvidenceRecord",
    "InvestmentCase",
    "InvestmentCaseRequest",
    "NumericClaim",
    "OrderBundle",
    "OrderIntent",
    "RightsManifest",
    "RiskDecisionPayload",
    "SignedRiskDecision",
    "ToolAuthorizationRequest",
]
