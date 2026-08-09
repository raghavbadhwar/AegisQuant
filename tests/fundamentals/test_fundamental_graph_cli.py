from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aegis.fundamentals import FixtureFundamentalProvider, load_fundamental_fixture
from aegis.fundamentals.graph import (
    FundamentalGraphError,
    run_fundamental_graph,
)
from apps.cli import app

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data/fixtures/fundamentals/cmpd.json"
EXPECTED_ROLES = {
    "business_industry",
    "financial_quality",
    "growth_drivers",
    "accounting_quality",
    "balance_sheet",
    "capital_allocation",
    "management_guidance",
    "valuation",
    "catalysts_risks",
}


def test_fundamental_graph_is_deterministic_and_binds_driver_proposer() -> None:
    request, _, _ = load_fundamental_fixture(FIXTURE)
    provider = FixtureFundamentalProvider(FIXTURE)
    first = run_fundamental_graph(request, provider)
    second = run_fundamental_graph(request, provider)
    assert first == second
    assert all("persona" not in artifact.role for artifact in first.specialist_artifacts)
    assert len({artifact.producer for artifact in first.specialist_artifacts}) == 9
    assert all(
        driver.proposer_artifact_id is None
        for forecast in first.forecasts.values()
        for driver in forecast.drivers
    )


def test_graph_rejects_missing_specialist_and_evidence_widening() -> None:
    request, _, _ = load_fundamental_fixture(FIXTURE)
    base = FixtureFundamentalProvider(FIXTURE)

    class MissingProvider:
        def load(self, request):  # type: ignore[no-untyped-def]
            return base.load(request)

        def analyze_role(self, request, role_input):  # type: ignore[no-untyped-def]
            artifact = base.analyze_role(request, role_input)
            if role_input.role == "catalysts_risks":
                return artifact.model_copy(update={"role": "business_industry"})
            return artifact

    with pytest.raises(FundamentalGraphError, match="every specialist"):
        run_fundamental_graph(request, MissingProvider())

    class WideningProvider:
        def load(self, request):  # type: ignore[no-untyped-def]
            return base.load(request)

        def analyze_role(self, request, role_input):  # type: ignore[no-untyped-def]
            artifact = base.analyze_role(request, role_input)
            if role_input.role != "business_industry":
                return artifact
            claim = artifact.claims[0].model_copy(update={"evidence_ids": ["widened"]})
            from aegis.contracts import FundamentalSpecialistArtifact
            from aegis.fundamentals.hashing import build_hashed

            values = artifact.model_dump(exclude={"content_hash"})
            values["claims"] = [claim]
            return build_hashed(FundamentalSpecialistArtifact, **values)

    with pytest.raises(FundamentalGraphError, match="evidence widening"):
        run_fundamental_graph(request, WideningProvider())


def test_company_research_cli_is_fund_independent_and_replay_safe(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "research",
            "company",
            "CMPD",
            "--as-of",
            "2025-06-30",
            "--fixture",
            str(FIXTURE),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"dossier_id":"fundamental-dossier-cmpd-research-20250630"' in result.output
    output = tmp_path / "dossier.md"
    rendered = runner.invoke(
        app,
        [
            "research",
            "company",
            "CMPD",
            "--as-of",
            "2025-06-30",
            "--fixture",
            str(FIXTURE),
            "--output",
            str(output),
        ],
    )
    assert rendered.exit_code == 0, rendered.output
    markdown = output.read_text()
    assert "Fundamental Research Dossier" in markdown
    assert "## Operating Forecasts and Drivers" in markdown
    assert "## DCF Assumptions and Sensitivities" in markdown
    assert "fundamental-metrics-v1:2024-12-31:net_debt" in markdown
    assert "| Year | Revenue | Operating margin | NOPAT | FCFF | Diluted shares |" in markdown


def test_fundamental_role_manifests_match_runtime_contract() -> None:
    for role in EXPECTED_ROLES:
        agent_text = (ROOT / "aegis" / "agents" / f"fundamental_{role}" / "AGENT.md").read_text()
        skill_text = (
            ROOT / "skills" / f"fundamental-{role.replace('_', '-')}" / "SKILL.md"
        ).read_text()
        for text in (agent_text, skill_text):
            assert "FundamentalSpecialistInput" in text
            assert "FundamentalSpecialistArtifact" in text
            assert "FundamentalAssessment" not in text
            assert "Do not recompute" in text or "No raw sizing" in text


def test_role_semantics_match_typed_assessments_through_released_graph() -> None:
    for fixture_name, expected_accounting in (
        ("cmpd.json", "supportive"),
        ("warn.json", "cautionary"),
    ):
        fixture = ROOT / "data/fixtures/fundamentals" / fixture_name
        request, _, _ = load_fundamental_fixture(fixture)
        result = run_fundamental_graph(request, FixtureFundamentalProvider(fixture))
        assert result.release_status == "committee_verified"
        assert result.accounting is not None
        accounting_claim = next(
            artifact.claims[0]
            for artifact in result.specialist_artifacts
            if artifact.role == "accounting_quality"
        )
        assert accounting_claim.conclusion == expected_accounting
        assert "accounting=" in accounting_claim.statement
        if (
            result.accounting.accrual_warning
            or result.accounting.sbc_warning
            or result.accounting.acquisition_warning
        ):
            assert accounting_claim.conclusion != "supportive"
        growth_claim = next(
            artifact.claims[0]
            for artifact in result.specialist_artifacts
            if artifact.role == "growth_drivers"
        )
        balance_claim = next(
            artifact.claims[0]
            for artifact in result.specialist_artifacts
            if artifact.role == "balance_sheet"
        )
        catalyst_claim = next(
            artifact.claims[0]
            for artifact in result.specialist_artifacts
            if artifact.role == "catalysts_risks"
        )
        assert "growth=" in growth_claim.statement and "revenue=" not in growth_claim.statement
        assert "balance_sheet=" in balance_claim.statement
        assert "catalyst=" in catalyst_claim.statement

    guide_fixture = ROOT / "data/fixtures/fundamentals/guide.json"
    guide_request, _, _ = load_fundamental_fixture(guide_fixture)
    guide = run_fundamental_graph(guide_request, FixtureFundamentalProvider(guide_fixture))
    management_claim = next(
        artifact.claims[0]
        for artifact in guide.specialist_artifacts
        if artifact.role == "management_guidance"
    )
    assert guide.management is not None and guide.management.hit_rate == 0.0
    assert management_claim.conclusion == "cautionary"
    assert "management=-1.0" in management_claim.statement


def test_specialist_conclusions_are_calculation_first_and_all_abstain_is_typed() -> None:
    request, _, _ = load_fundamental_fixture(FIXTURE)
    base = FixtureFundamentalProvider(FIXTURE)
    baseline = run_fundamental_graph(request, base)
    assert baseline.business is not None
    business_artifact = next(
        item for item in baseline.specialist_artifacts if item.role == "business_industry"
    )
    assert baseline.business.summary == business_artifact.claims[0].statement
    assert set(baseline.specialist_findings) == EXPECTED_ROLES
    assert baseline.committee_decision is not None
    assert baseline.release_status == "committee_verified"
    _, snapshot, inputs = load_fundamental_fixture(FIXTURE)
    from aegis.fundamentals import compute_preliminary_research
    from aegis.reporting import dossier_json

    preliminary = compute_preliminary_research(request, snapshot, inputs)
    assert preliminary.release_status == "preliminary"
    assert preliminary.committee_decision is None
    with pytest.raises(ValueError, match="not a releasable dossier"):
        dossier_json(preliminary)

    class ContradictingProvider:
        def load(self, request):  # type: ignore[no-untyped-def]
            return base.load(request)

        def analyze_role(self, request, role_input):  # type: ignore[no-untyped-def]
            artifact = base.analyze_role(request, role_input)
            if role_input.role != "business_industry":
                return artifact
            claim = artifact.claims[0]
            predicate = claim.predicates[0]
            opposite = "lt" if predicate.operator in {"gt", "ge"} else "gt"
            changed_predicate = predicate.model_copy(update={"operator": opposite})
            changed_conclusion = "cautionary" if opposite == "lt" else "supportive"
            changed_claim = claim.model_copy(
                update={
                    "conclusion": changed_conclusion,
                    "statement": next(
                        f"{artifact.role} assessment is {changed_conclusion}: verified "
                        f"{calculation.output_name}={calculation.output_value} from "
                        f"{calculation.calculation_id} satisfies "
                        f"{changed_predicate.operator} "
                        f"{changed_predicate.reference_value}."
                        for calculation in role_input.calculation_lineage
                        if calculation.calculation_id == changed_predicate.calculation_id
                    ),
                    "predicates": [changed_predicate],
                }
            )
            from aegis.contracts import FundamentalSpecialistArtifact
            from aegis.fundamentals.hashing import build_hashed

            values = artifact.model_dump(exclude={"content_hash"})
            values["claims"] = [changed_claim]
            return build_hashed(FundamentalSpecialistArtifact, **values)

    with pytest.raises(FundamentalGraphError, match="contradicts verified calculations"):
        run_fundamental_graph(request, ContradictingProvider())

    class ThresholdWideningProvider:
        def load(self, request):  # type: ignore[no-untyped-def]
            return base.load(request)

        def analyze_role(self, request, role_input):  # type: ignore[no-untyped-def]
            artifact = base.analyze_role(request, role_input)
            if role_input.role != "business_industry":
                return artifact
            claim = artifact.claims[0]
            predicate = claim.predicates[0].model_copy(
                update={"operator": "ge", "reference_value": Decimal("0")}
            )
            calculation = next(
                item
                for item in role_input.calculation_lineage
                if item.calculation_id == predicate.calculation_id
            )
            changed_claim = claim.model_copy(
                update={
                    "statement": (
                        f"{artifact.role} assessment is {claim.conclusion}: verified "
                        f"{calculation.output_name}={calculation.output_value} from "
                        f"{calculation.calculation_id} satisfies "
                        f"{predicate.operator} {predicate.reference_value}."
                    ),
                    "predicates": [predicate],
                }
            )
            from aegis.contracts import FundamentalSpecialistArtifact
            from aegis.fundamentals.hashing import build_hashed

            values = artifact.model_dump(exclude={"content_hash"})
            values["claims"] = [changed_claim]
            return build_hashed(FundamentalSpecialistArtifact, **values)

    with pytest.raises(FundamentalGraphError, match="role-specific semantics"):
        run_fundamental_graph(request, ThresholdWideningProvider())

    class AbstainingProvider:
        def load(self, request):  # type: ignore[no-untyped-def]
            return base.load(request)

        def analyze_role(self, request, role_input):  # type: ignore[no-untyped-def]
            from aegis.contracts import FundamentalSpecialistArtifact
            from aegis.fundamentals.hashing import build_hashed

            artifact = base.analyze_role(request, role_input)
            values = artifact.model_dump(exclude={"content_hash"})
            values.update(
                {
                    "claims": [],
                    "abstained": True,
                    "abstain_reason": "insufficient evidence",
                }
            )
            return build_hashed(FundamentalSpecialistArtifact, **values)

    result = run_fundamental_graph(request, AbstainingProvider())
    assert result.abstained and result.alpha_forecast.abstained
    assert "required specialists abstained" in (result.abstain_reason or "")
