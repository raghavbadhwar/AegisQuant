from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from aegis.contracts import Claim, ClaimEdge, EvidenceAuditPolicy, NumericClaim
from aegis.data import FixtureDataClient
from aegis.evidence import EvidenceLedger, audit_evidence, build_claim_graph
from aegis.fund.models import FixtureForecastProvider, ForecastIntegrityError, load_replay_manifest
from aegis.harness.agent_loader import load_agent_tree
from aegis.harness.graph import LangGraphForecastProvider
from aegis.harness.model_router import ReplayModelProvider
from aegis.harness.skill_loader import load_skill_tree
from aegis.memory import LocalMemoryBackend, build_memory_candidate, build_memory_decision

ROOT = Path(__file__).resolve().parents[2]


def components():  # type: ignore[no-untyped-def]
    manifest = load_replay_manifest(ROOT / "data/fixtures/cases/nvda_earnings_case.json")
    case = manifest.research_case()
    data = FixtureDataClient(ROOT / "data/fixtures")
    snapshot = data.latest_snapshot(case.tickers, case.as_of)
    fixture = FixtureForecastProvider(
        ROOT / manifest.forecast_fixture, ROOT / manifest.evidence_fixture
    )
    preflight = fixture.research(case, snapshot)
    return manifest, case, snapshot, preflight


def make_provider(
    model: ReplayModelProvider | None = None, memory: LocalMemoryBackend | None = None
):  # type: ignore[no-untyped-def]
    manifest, case, snapshot, preflight = components()
    model = model or ReplayModelProvider(ROOT / manifest.agent_output_fixture, case.case_id)
    provider = LangGraphForecastProvider(
        model,
        load_skill_tree(ROOT / "skills"),
        load_agent_tree(ROOT / "aegis/agents"),
        preflight.evidence,
        memory,
    )
    return case, snapshot, provider


def changed_model(
    tmp_path: Path,
    updates: dict[str, dict[str, Any]] | None = None,
    missing_role: str | None = None,
) -> ReplayModelProvider:
    payload = json.loads((ROOT / "data/fixtures/agent_outputs.json").read_text())
    if missing_role:
        del payload["roles"][missing_role]
    for role, role_updates in (updates or {}).items():
        payload["roles"][role].update(role_updates)
    path = tmp_path / "agent_outputs.json"
    path.write_text(json.dumps(payload, sort_keys=True))
    return ReplayModelProvider(path, "nvda-earnings-demo")


def test_full_graph_dossier_is_deterministic_and_complete() -> None:
    case, snapshot, first_provider = make_provider()
    _, _, second_provider = make_provider()
    first = first_provider.research(case, snapshot)
    second = second_provider.research(case, snapshot)
    assert first == second
    assert len(first.artifacts) == 10
    assert [event.sequence for event in first.graph_events] == list(range(10))
    assert {artifact.producer_agent for artifact in first.artifacts} == {
        "coordinator",
        "quant",
        "fundamentals",
        "event-behavioral",
        "evidence-auditor",
        "bull",
        "bear",
        "base-rate",
        "cio",
        "verifier",
    }
    assert all(not forecast.abstained for forecast in first.forecasts)
    assert all(artifact.prompt_versions for artifact in first.artifacts)
    assert first.claim_graph is not None
    assert first.claim_graph.numeric_claims
    assert all(claim.calculation_id for claim in first.claim_graph.numeric_claims)
    assert first.evidence_audit is not None and first.evidence_audit.approved


def test_bull_bear_and_base_rate_openings_are_independent() -> None:
    case, snapshot, provider = make_provider()
    dossier = provider.research(case, snapshot)
    by_role = {artifact.producer_agent: artifact for artifact in dossier.artifacts}
    input_hashes = {
        by_role[role].payload["opening_input_hash"] for role in ("bull", "bear", "base-rate")
    }
    assert len(input_hashes) == 1
    assert "bear" not in str(by_role["bull"].payload["output"]).lower()
    assert "bull" not in str(by_role["bear"].payload["output"]).lower()


@pytest.mark.parametrize(
    "role",
    [
        "coordinator",
        "quant",
        "fundamentals",
        "event-behavioral",
        "evidence-auditor",
        "bull",
        "bear",
        "base-rate",
        "cio",
        "verifier",
    ],
)
def test_any_model_failure_forces_explicit_abstention(role: str, tmp_path: Path) -> None:
    case, snapshot, provider = make_provider(changed_model(tmp_path, missing_role=role))
    dossier = provider.research(case, snapshot)
    assert all(forecast.abstained for forecast in dossier.forecasts)
    assert all(forecast.abstain_reason for forecast in dossier.forecasts)
    if role == "evidence-auditor":
        downstream = {"bull", "bear", "base-rate", "cio", "verifier"}
        assert all(
            not artifact.evidence_ids
            for artifact in dossier.artifacts
            if artifact.producer_agent in downstream
        )


def test_cio_cannot_introduce_evidence_outside_approved_bundle(tmp_path: Path) -> None:
    model = changed_model(tmp_path, {"cio": {"evidence_ids": ["rogue-evidence"]}})
    case, snapshot, provider = make_provider(model)
    with pytest.raises(ForecastIntegrityError, match="outside the approved bundle"):
        provider.research(case, snapshot)


def test_explicit_evidence_auditor_block_halts_case(tmp_path: Path) -> None:
    model = changed_model(tmp_path, {"evidence-auditor": {"approved": False}})
    case, snapshot, provider = make_provider(model)
    with pytest.raises(ForecastIntegrityError, match="auditor blocked"):
        provider.research(case, snapshot)


def test_downstream_roles_cannot_cite_unapproved_evidence(tmp_path: Path) -> None:
    approved = ["demo-aapl-20240223-price"]
    model = changed_model(
        tmp_path,
        {
            "evidence-auditor": {"evidence_ids": approved},
            "bull": {"evidence_ids": approved},
            "bear": {"evidence_ids": approved},
            "base-rate": {"evidence_ids": approved},
        },
    )
    case, snapshot, provider = make_provider(model)
    with pytest.raises(ForecastIntegrityError, match="outside the approved bundle"):
        provider.research(case, snapshot)


def test_missing_cio_forecasts_forces_abstention(tmp_path: Path) -> None:
    model = changed_model(tmp_path, {"cio": {"forecasts": []}})
    case, snapshot, provider = make_provider(model)
    dossier = provider.research(case, snapshot)
    assert all(forecast.abstained for forecast in dossier.forecasts)


class FalseReportingProvider:
    network_enabled = False


def test_replay_graph_rejects_unsealed_model_provider() -> None:
    _, _, _, preflight = components()
    with pytest.raises(ValueError, match="sealed ReplayModelProvider"):
        LangGraphForecastProvider(
            FalseReportingProvider(),  # type: ignore[arg-type]
            load_skill_tree(ROOT / "skills"),
            load_agent_tree(ROOT / "aegis/agents"),
            preflight.evidence,
        )


def test_graph_context_retrieves_only_governed_point_in_time_memory(tmp_path: Path) -> None:
    _, case, _, preflight = components()
    prior_bundle = preflight.evidence.model_copy(update={"case_id": "prior-case"})
    claim = Claim(
        claim_id="memory-lineage-claim",
        case_id="prior-case",
        statement="NVDA evidence is approved for memory lineage.",
        claim_type="factual",
        material=True,
        evidence_ids=["demo-nvda-20240223-price"],
    )
    edge = ClaimEdge(
        edge_id="memory-lineage-support",
        source_kind="evidence",
        source_id="demo-nvda-20240223-price",
        relation="SUPPORTS",
        target_kind="claim",
        target_id=claim.claim_id,
    )
    graph = build_claim_graph("prior-case", [claim], [], [edge])
    audit = audit_evidence(prior_bundle, graph, EvidenceAuditPolicy())
    evidence_ledger = EvidenceLedger(tmp_path / "evidence.sqlite")
    evidence_ledger.append(prior_bundle, graph, audit)
    backend = LocalMemoryBackend(tmp_path / "memory.sqlite", evidence_ledger=evidence_ledger)
    candidate_payload = {
        "candidate_id": "graph-memory-candidate",
        "memory_id": "graph-memory",
        "proposer_id": "postmortem",
        "memory_type": "prior-case",
        "title": "NVDA prior earnings pattern",
        "statement": "NVDA demand surprises sometimes persist after earnings.",
        "evidence_ids": ["demo-nvda-20240223-price"],
        "source_case_ids": ["prior-case"],
        "entity_ids": ["NVDA"],
        "scope": "entity",
        "confidence": 0.7,
        "utility_score": 0.8,
        "created_at": case.as_of - timedelta(days=1),
        "expires_at": case.as_of + timedelta(days=30),
        "review_by": case.as_of + timedelta(days=1),
    }
    candidate = build_memory_candidate(**candidate_payload)
    backend.stage(candidate)
    decision_payload = {
        "decision_id": "graph-memory-approval",
        "candidate_id": candidate.candidate_id,
        "candidate_hash": candidate.content_hash,
        "evaluator_id": "human-reviewer",
        "decision": "approve",
        "reason": "Approved for bounded replay context.",
        "decided_at": case.as_of,
    }
    backend.decide(build_memory_decision(**decision_payload))
    case, snapshot, provider = make_provider(memory=backend)
    dossier = provider.research(case, snapshot)
    assert [hit.item.memory_id for hit in dossier.memory_hits] == ["graph-memory"]
    assert dossier.memory_snapshot_hash == backend.snapshot(case.as_of).content_hash
    assert all(artifact.payload["input_hash"] for artifact in dossier.artifacts)


class FalseReportingMemoryReader:
    def search(self, query):  # type: ignore[no-untyped-def]
        raise AssertionError("unsealed memory reader must not be invoked")

    def snapshot(self, as_of):  # type: ignore[no-untyped-def]
        raise AssertionError("unsealed memory reader must not be invoked")


def test_replay_graph_rejects_unsealed_memory_reader() -> None:
    manifest, case, _, preflight = components()
    with pytest.raises(ValueError, match="sealed LocalMemoryBackend"):
        LangGraphForecastProvider(
            ReplayModelProvider(ROOT / manifest.agent_output_fixture, case.case_id),
            load_skill_tree(ROOT / "skills"),
            load_agent_tree(ROOT / "aegis/agents"),
            preflight.evidence,
            FalseReportingMemoryReader(),  # type: ignore[arg-type]
        )


def test_nonexistent_calculation_id_blocks_numeric_claim() -> None:
    _, _, _, preflight = components()
    evidence = preflight.evidence.records[0]
    claim = Claim(
        claim_id="numeric-made-up",
        case_id=preflight.case_id,
        statement="Made-up exact number.",
        claim_type="numeric",
        material=True,
        evidence_ids=[evidence.evidence_id],
    )
    numeric = NumericClaim(
        claim_id=claim.claim_id,
        name="made_up",
        value=Decimal("123"),
        unit="ratio",
        evidence_id=evidence.evidence_id,
        coordinates="forecast_id=self;field=value",
        calculation_id="made-up-nonexistent-calculation",
    )
    edges = [
        ClaimEdge(
            edge_id="made-up-support",
            source_kind="evidence",
            source_id=evidence.evidence_id,
            relation="SUPPORTS",
            target_kind="claim",
            target_id=claim.claim_id,
        ),
        ClaimEdge(
            edge_id="made-up-derived",
            source_kind="claim",
            source_id=claim.claim_id,
            relation="DERIVED_BY",
            target_kind="calculation",
            target_id=numeric.calculation_id or "missing",
        ),
    ]
    graph = build_claim_graph(preflight.case_id, [claim], [numeric], edges)
    audit = audit_evidence(preflight.evidence, graph, EvidenceAuditPolicy())
    assert not audit.approved
    assert any(finding.code == "numeric-provenance" for finding in audit.findings)


def test_cio_exact_number_must_match_registered_deterministic_calculation(
    tmp_path: Path,
) -> None:
    outputs = json.loads((ROOT / "data/fixtures/agent_outputs.json").read_text())
    outputs["roles"]["cio"]["forecasts"][0]["expected_excess_return"] = 0.086
    path = tmp_path / "mutated-cio.json"
    path.write_text(json.dumps(outputs))
    case, snapshot, provider = make_provider(ReplayModelProvider(path, "nvda-earnings-demo"))
    with pytest.raises(ForecastIntegrityError, match="deterministic calculation"):
        provider.research(case, snapshot)
