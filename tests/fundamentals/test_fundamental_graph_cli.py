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
    from aegis.fundamentals.service import _compute_preliminary_research
    from aegis.reporting import dossier_json

    preliminary = _compute_preliminary_research(request, snapshot, inputs)
    assert preliminary.release_status == "preliminary"
    assert preliminary.committee_decision is None
    assert preliminary.alpha_forecast.abstained
    assert preliminary.alpha_forecast.verification_status == "pending"
    assert preliminary.alpha_forecast.expected_excess_return is None
    with pytest.raises(ValueError, match="not a releasable dossier"):
        dossier_json(preliminary)
    from aegis.contracts import FundamentalResearchDossier
    from aegis.fundamentals.hashing import build_hashed

    forged_values = {
        name: getattr(preliminary, name)
        for name in type(preliminary).model_fields
        if name != "content_hash"
    }
    forged_values["alpha_forecast"] = baseline.alpha_forecast
    with pytest.raises(ValueError, match="pending forecast abstention"):
        build_hashed(FundamentalResearchDossier, **forged_values)

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


def test_public_api_and_verified_forecast_enforce_committee_authority() -> None:
    import aegis.fundamentals as fundamentals
    from aegis.reporting import dossier_markdown

    assert "compute_preliminary_research" not in fundamentals.__all__
    assert not hasattr(fundamentals, "compute_preliminary_research")
    request, _, _ = load_fundamental_fixture(FIXTURE)
    verified = run_fundamental_graph(request, FixtureFundamentalProvider(FIXTURE))
    committee = verified.committee_decision
    assert verified.release_status == "committee_verified"
    assert committee is not None and committee.decision == "approved"
    assert not verified.alpha_forecast.abstained
    assert verified.alpha_forecast.verification_status == "committee_verified"
    assert verified.alpha_forecast.committee_id == committee.committee_id
    assert verified.alpha_forecast.committee_content_hash == committee.content_hash
    assert verified.alpha_forecast.source_dossier_id == verified.dossier_id
    assert committee.request_id == request.request_id
    assert committee.specialist_artifact_ids == sorted(
        artifact.artifact_id for artifact in verified.specialist_artifacts
    )
    assert sorted(committee.accepted_claim_ids) == sorted(
        claim.claim_id for artifact in verified.specialist_artifacts for claim in artifact.claims
    )
    assert committee.evidence_ids == verified.evidence_ids
    assert committee.calculation_ids == verified.calculation_ids

    reordered = verified.model_copy(
        update={
            "dcf": {
                name: dcf.model_copy(
                    update={"calculation_ids": list(reversed(dcf.calculation_ids))}
                )
                for name, dcf in verified.dcf.items()
            },
            "reverse_dcf": {
                name: reverse.model_copy(
                    update={"calculation_ids": list(reversed(reverse.calculation_ids))}
                )
                for name, reverse in verified.reverse_dcf.items()
            },
        }
    )
    markdown = dossier_markdown(reordered)
    for dcf in verified.dcf.values():
        primary_id = f"dcf-v1:{dcf.forecast_id}:value_per_share"
        assert primary_id in markdown
        for point in dcf.sensitivity:
            assert (
                f"{point.discount_rate:.2%} [calc: {point.discount_rate_calculation_id}]"
            ) in markdown
            assert (
                f"{point.terminal_growth:.2%} [calc: {point.terminal_growth_calculation_id}]"
            ) in markdown
            assert (
                f"{point.enterprise_value} [calc: {point.enterprise_value_calculation_id}]"
            ) in markdown
            assert (
                f"{point.equity_value_per_share} "
                f"[calc: {point.equity_value_per_share_calculation_id}]"
            ) in markdown


def test_approved_graph_computes_numeric_core_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import aegis.fundamentals.graph as graph_module

    request, snapshot, inputs = load_fundamental_fixture(FIXTURE)
    preliminary = graph_module._compute_preliminary_research(request, snapshot, inputs)
    original = graph_module._compute_preliminary_research
    calls = 0

    def counted(request, snapshot, inputs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return original(request, snapshot, inputs)

    monkeypatch.setattr(graph_module, "_compute_preliminary_research", counted)
    verified = graph_module.run_fundamental_graph(request, FixtureFundamentalProvider(FIXTURE))
    assert calls == 1
    assert verified.calculation_ids == preliminary.calculation_ids
    assert verified.calculation_lineage == preliminary.calculation_lineage
    assert verified.evidence_ids == preliminary.evidence_ids
    assert verified.forecasts == preliminary.forecasts
    assert verified.dcf == preliminary.dcf


def test_finalizer_preserves_reordered_additional_thesis_claims() -> None:
    from aegis.contracts import FundamentalResearchDossier, ThesisClaim
    from aegis.fundamentals.hashing import build_hashed
    from aegis.fundamentals.service import (
        _compute_preliminary_research,
        _finalize_verified_research,
    )
    from aegis.fundamentals.thesis import build_thesis

    request, snapshot, inputs = load_fundamental_fixture(FIXTURE)
    preliminary = _compute_preliminary_research(request, snapshot, inputs)
    verified = run_fundamental_graph(request, FixtureFundamentalProvider(FIXTURE))
    assert preliminary.thesis is not None and verified.committee_decision is not None
    prior = preliminary.thesis
    extra = ThesisClaim(
        claim_id=f"thesis-{request.request_id}-secondary",
        statement="A secondary audited claim must survive finalization.",
        status="active",
        evidence_ids=preliminary.evidence_ids,
        calculation_ids=[preliminary.calculation_ids[0]],
    )
    reordered_thesis = build_thesis(
        thesis_id=prior.thesis_id,
        ticker=prior.ticker,
        version=prior.version,
        as_of=prior.as_of,
        horizon_days=prior.horizon_days,
        core_claims=[extra, *prior.core_claims],
        catalysts=prior.catalysts,
        risks=prior.risks,
        invalidation_conditions=prior.invalidation_conditions,
        valuation_case_ids=prior.valuation_case_ids,
        checkpoints=prior.checkpoints,
        supersedes_thesis_id=prior.supersedes_thesis_id,
        status=prior.status,
        contract_version="3.0.0",
    )
    preliminary_values = {
        name: getattr(preliminary, name)
        for name in type(preliminary).model_fields
        if name != "content_hash"
    }
    preliminary_values["thesis"] = reordered_thesis
    reordered_preliminary = build_hashed(FundamentalResearchDossier, **preliminary_values)
    finalized = _finalize_verified_research(
        reordered_preliminary,
        inputs,
        tuple(verified.specialist_artifacts),
        verified.committee_decision,
    )
    assert finalized.thesis is not None
    claims = {claim.claim_id: claim for claim in finalized.thesis.core_claims}
    assert next(claim.claim_id for claim in finalized.thesis.core_claims) == extra.claim_id
    assert claims[extra.claim_id].statement == extra.statement
    primary = claims[f"thesis-{request.request_id}-core"]
    assert "Specialist review:" in primary.statement
