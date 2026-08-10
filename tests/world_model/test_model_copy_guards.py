from datetime import UTC, datetime

import pytest

from aegis.causal.beliefs import BeliefState
from aegis.causal.contracts import CausalEdge, CausalGraphSnapshot, IdentificationRecord
from aegis.causal.mechanisms import MechanismDefinition
from aegis.contracts._base import CandidateContractModel
from aegis.reporting.traceability import (
    EngineeringTraceabilityReport,
    RunLedgerReceiptReference,
    SnapshotReference,
    SourceProvenanceReference,
    StrategyComparisonReadiness,
    TraceabilityReceiptReference,
)
from aegis.research_planner.contracts import ResearchAction, ValueOfInformationResult
from aegis.world_model.contracts import (
    ScenarioIntervention,
    VariableProvenance,
    WorldSnapshot,
    WorldVariable,
)
from aegis.world_model.contributions import (
    EffectContribution,
    EffectContributionLedger,
    TargetEffectReconciliation,
)
from aegis.world_model.counterfactual import (
    CausalMechanismApproval,
    CounterfactualOutcome,
    CounterfactualRequest,
)
from aegis.world_model.domain_pack import DomainPackManifest
from aegis.world_model.experiments import (
    TemporalEvaluationPlan,
    TemporalSplit,
    WorldModelExperimentLedger,
    WorldModelExperimentManifest,
)
from aegis.world_model.scenario import CompiledScenario, ScenarioResult
from aegis.world_model.twin import InvariantViolation, TwinState, TwinTransition
from aegis.world_model.uncertainty import DistributionSpec, UncertaintyDecomposition


def test_world_variable_model_copy_revalidates_observed_evidence_requirement() -> None:
    variable = WorldVariable(
        variable_id="supplier.revenue",
        value=10.0,
        unit="usd_millions",
        provenance=VariableProvenance.OBSERVED,
        available_at=datetime(2024, 1, 1, tzinfo=UTC),
        evidence_ids=("filing-1",),
        uncertainty_label="measured",
    )

    with pytest.raises(ValueError, match="observed world variable requires evidence"):
        variable.model_copy(update={"evidence_ids": ()})


def test_candidate_model_copy_rejects_unknown_fields() -> None:
    variable = WorldVariable(
        variable_id="supplier.revenue",
        value=10.0,
        unit="usd_millions",
        provenance=VariableProvenance.OBSERVED,
        available_at=datetime(2024, 1, 1, tzinfo=UTC),
        evidence_ids=("filing-1",),
        uncertainty_label="measured",
    )

    with pytest.raises(ValueError, match="unknown fields"):
        variable.model_copy(update={"unexpected": "value"})


def test_every_public_v4_candidate_contract_uses_the_revalidating_base() -> None:
    candidate_contracts = (
        BeliefState,
        IdentificationRecord,
        CausalEdge,
        CausalGraphSnapshot,
        MechanismDefinition,
        WorldVariable,
        WorldSnapshot,
        ScenarioIntervention,
        CompiledScenario,
        ScenarioResult,
        InvariantViolation,
        TwinState,
        TwinTransition,
        EffectContribution,
        TargetEffectReconciliation,
        EffectContributionLedger,
        DomainPackManifest,
        TemporalSplit,
        TemporalEvaluationPlan,
        WorldModelExperimentManifest,
        WorldModelExperimentLedger,
        DistributionSpec,
        UncertaintyDecomposition,
        CausalMechanismApproval,
        CounterfactualRequest,
        CounterfactualOutcome,
        ResearchAction,
        ValueOfInformationResult,
        SourceProvenanceReference,
        SnapshotReference,
        RunLedgerReceiptReference,
        StrategyComparisonReadiness,
        TraceabilityReceiptReference,
        EngineeringTraceabilityReport,
    )

    assert all(issubclass(contract, CandidateContractModel) for contract in candidate_contracts)
