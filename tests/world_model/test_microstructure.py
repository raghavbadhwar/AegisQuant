from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegis.world_model.microstructure import (
    V3_SIMULATED_EXECUTION_BOUNDARY_ID,
    DeterministicMicrostructureResearchAdapter,
    MicrostructureAdapterConfig,
    MicrostructureScenario,
    MicrostructureStatus,
    probe_external_microstructure_adapter,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _scenario() -> MicrostructureScenario:
    return MicrostructureScenario(
        scenario_id="microstructure-stress-v1",
        as_of=NOW,
        scenario_run_hash="a" * 64,
        regime_id="stress",
        liquidity_stress=0.4,
        participation_rate=0.25,
        latency_stress_ms=5,
        assumption_ids=("candidate-liquidity-stress",),
    ).sealed()


def _config() -> MicrostructureAdapterConfig:
    return MicrostructureAdapterConfig(
        config_id="deterministic-microstructure-v1",
        base_latency_ms=2,
        max_candidate_impact_bps=20.0,
        max_candidate_slippage_bps=10.0,
        supported_regimes=("normal", "stress"),
    ).sealed()


def test_microstructure_research_adapter_is_deterministic_and_isolated() -> None:
    adapter = DeterministicMicrostructureResearchAdapter()

    first = adapter.simulate(_scenario(), _config())
    repeated = adapter.simulate(_scenario(), _config())

    assert first.model_dump_json() == repeated.model_dump_json()
    assert first.status == MicrostructureStatus.CANDIDATE_RESEARCH
    assert first.execution_boundary_id == V3_SIMULATED_EXECUTION_BOUNDARY_ID
    assert first.candidate_impact_bps == 2.0
    assert first.candidate_latency_ms == 7
    assert first.authority == "candidate_only"


def test_microstructure_adapter_abstains_for_unsupported_regimes() -> None:
    scenario = (
        _scenario().model_copy(update={"regime_id": "unsupported", "content_hash": None}).sealed()
    )

    outcome = DeterministicMicrostructureResearchAdapter().simulate(scenario, _config())

    assert outcome.status == MicrostructureStatus.ABSTAINED
    assert outcome.reason == "unsupported_regime"
    assert outcome.candidate_impact_bps is None


def test_microstructure_contract_rejects_order_authority_fields() -> None:
    payload = _scenario().model_dump(mode="json", exclude={"content_hash"})
    payload["orders"] = ("forbidden",)

    with pytest.raises(ValueError, match="Extra inputs"):
        MicrostructureScenario.model_validate(payload)


def test_microstructure_adapter_isolated_from_the_v3_execution_path() -> None:
    source = (Path(__file__).parents[2] / "aegis/world_model/microstructure.py").read_text()

    assert "aegis.brokers" not in source
    assert "aegis.fund.execution" not in source
    assert "aegis.fund.run_cycle" not in source


def test_unapproved_external_microstructure_adapters_explicitly_abstain() -> None:
    outcome = probe_external_microstructure_adapter("abides")

    assert outcome.status == "abstained"
    assert outcome.reason == "integration_not_approved"
    assert outcome.authority == "candidate_only"
