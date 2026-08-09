from __future__ import annotations

from pathlib import Path

import pytest

from aegis.harness.budgets import BudgetExceeded
from aegis.harness.capability_broker import CapabilityBroker, CapabilityDenied
from aegis.harness.model_router import ModelProviderError, ReplayModelProvider
from aegis.harness.skill_loader import SkillValidationError, load_skill, load_skill_tree

ROOT = Path(__file__).resolve().parents[2]


def test_all_release1_skills_load_with_stable_versions() -> None:
    skills = load_skill_tree(ROOT / "skills")
    assert len(skills) == 20
    assert all(skill.metadata.version == "1.0.0" for skill in skills.values())
    assert all(len(skill.content_hash) == 64 for skill in skills.values())


def test_skill_loader_rejects_path_escape_and_missing_sections(tmp_path: Path) -> None:
    outside = tmp_path / "outside/SKILL.md"
    outside.parent.mkdir()
    outside.write_text("---\nname: bad\n---\n", encoding="utf-8")
    root = tmp_path / "allowed"
    root.mkdir()
    with pytest.raises(SkillValidationError, match="escapes"):
        load_skill(outside, root=root)
    with pytest.raises(SkillValidationError):
        load_skill(outside)


def test_capability_broker_denies_undeclared_and_capital_critical_tools() -> None:
    skill = load_skill(
        ROOT / "skills/specialist-research/quant-signal-analysis/SKILL.md",
        root=ROOT / "skills",
    )
    broker = CapabilityBroker("historical")
    broker.register("quant", skill)
    assert broker.decide("quant", skill, "data.price_snapshot").allowed
    assert not broker.decide("quant", skill, "broker.place_order").allowed
    with pytest.raises(CapabilityDenied):
        broker.authorize("quant", skill, "broker.place_order")


def test_capability_budget_is_runtime_enforced() -> None:
    skill = load_skill(ROOT / "skills/review-synthesis/bull-case/SKILL.md")
    broker = CapabilityBroker("replay")
    broker.register("bull", skill)
    broker.authorize("bull", skill, "artifact.read")
    broker.authorize("bull", skill, "artifact.read")
    with pytest.raises(BudgetExceeded):
        broker.authorize("bull", skill, "artifact.read")


def test_replay_model_provider_is_case_bound_and_deterministic() -> None:
    path = ROOT / "data/fixtures/agent_outputs.json"
    first = ReplayModelProvider(path, "nvda-earnings-demo")
    second = ReplayModelProvider(path, "nvda-earnings-demo")
    assert first.invoke("quant", "quant-code", "a" * 64) == second.invoke(
        "quant", "quant-code", "a" * 64
    )
    with pytest.raises(ModelProviderError):
        ReplayModelProvider(path, "wrong-case")


def test_replay_model_provider_normalizes_malformed_json(tmp_path: Path) -> None:
    fixture = tmp_path / "invalid.json"
    fixture.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ModelProviderError, match="invalid replay model fixture JSON"):
        ReplayModelProvider(fixture, "case")
