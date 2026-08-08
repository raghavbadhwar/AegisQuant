"""Public typed contracts for AegisQuant."""

from .artifacts import ResearchArtifact, canonical_json, canonical_sha256
from .case import ResearchCase, RunMode
from .claims import Claim, NumericClaim
from .evidence import EvidenceBundle, EvidenceRecord
from .execution import Fill, Order, OrderSide, OrderStatus, Position, SimulationMode
from .forecasts import AlphaForecast
from .learning import CandidateType, EvaluationStatus, LearningCandidate
from .memory import MemoryHit, MemoryItem, MemoryQuery, MemoryStatus
from .portfolio import PortfolioProposal
from .risk import RiskDecision, RiskPolicy
from .source import EventCandidate, ScrapeJob, SourceManifest, SourceRequest, SourceType

__all__ = [
    "AlphaForecast",
    "CandidateType",
    "Claim",
    "EvaluationStatus",
    "EventCandidate",
    "EvidenceBundle",
    "EvidenceRecord",
    "Fill",
    "LearningCandidate",
    "MemoryHit",
    "MemoryItem",
    "MemoryQuery",
    "MemoryStatus",
    "NumericClaim",
    "Order",
    "OrderSide",
    "OrderStatus",
    "PortfolioProposal",
    "Position",
    "ResearchArtifact",
    "ResearchCase",
    "RiskDecision",
    "RiskPolicy",
    "RunMode",
    "ScrapeJob",
    "SimulationMode",
    "SourceManifest",
    "SourceRequest",
    "SourceType",
    "canonical_json",
    "canonical_sha256",
]
