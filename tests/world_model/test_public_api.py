from pathlib import Path

import aegis.world_model as world_model


def test_world_model_exports_candidate_only_public_contracts() -> None:
    assert world_model.CompiledScenario
    assert world_model.DigitalTwin
    assert world_model.DomainPackManifest
    assert world_model.EffectContributionLedger
    assert world_model.TargetEffectReconciliation
    assert world_model.UncertaintyDecomposition
    assert world_model.WorldModelExperimentLedger
    assert world_model.WorldModelExperimentManifest
    assert world_model.CausalMechanismApproval
    assert world_model.CounterfactualRequest


def test_readme_links_to_the_candidate_only_v4_library_surface() -> None:
    readme = (Path(__file__).parents[2] / "README.md").read_text()

    assert "Candidate-only v4 world-model library" in readme
    assert "docs/V4_TRACEABILITY.md" in readme
    assert "hyperscaler.ai_capex_growth" in readme
