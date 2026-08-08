from __future__ import annotations

from pathlib import Path

import pytest

from aegis.data import FixtureDataClient
from aegis.fund.models import FixtureForecastProvider, ForecastIntegrityError, load_replay_manifest
from aegis.harness.graph import LangGraphForecastProvider
from aegis.harness.model_router import ModelProviderError, ReplayModelProvider
from aegis.harness.network_guard import NetworkAccessDenied
from aegis.harness.skill_loader import load_skill_tree

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


def make_provider(model=None):  # type: ignore[no-untyped-def]
    manifest, case, snapshot, preflight = components()
    model = model or ReplayModelProvider(ROOT / manifest.agent_output_fixture, case.case_id)
    provider = LangGraphForecastProvider(
        model,
        load_skill_tree(ROOT / "skills"),
        preflight.evidence,
    )
    return case, snapshot, provider


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


class FailingRoleProvider:
    network_enabled = False

    def __init__(self, role: str) -> None:
        self.role = role
        self.delegate = ReplayModelProvider(
            ROOT / "data/fixtures/agent_outputs.json", "nvda-earnings-demo"
        )

    def invoke(self, role: str, model_alias: str, input_hash: str):  # type: ignore[no-untyped-def]
        if role == self.role:
            raise ModelProviderError(f"injected {role} failure")
        return self.delegate.invoke(role, model_alias, input_hash)


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
def test_any_model_failure_forces_explicit_abstention(role: str) -> None:
    case, snapshot, provider = make_provider(FailingRoleProvider(role))
    dossier = provider.research(case, snapshot)
    assert all(forecast.abstained for forecast in dossier.forecasts)
    assert all(forecast.abstain_reason for forecast in dossier.forecasts)


class MutatingRoleProvider:
    network_enabled = False

    def __init__(self, role: str, updates: dict[str, object]) -> None:
        self.role = role
        self.updates = updates
        self.delegate = ReplayModelProvider(
            ROOT / "data/fixtures/agent_outputs.json", "nvda-earnings-demo"
        )

    def invoke(self, role: str, model_alias: str, input_hash: str):  # type: ignore[no-untyped-def]
        result = self.delegate.invoke(role, model_alias, input_hash)
        if role != self.role:
            return result
        output = {**result.output, **self.updates}
        return result.model_copy(update={"output": output})


def test_cio_cannot_introduce_evidence_outside_approved_bundle() -> None:
    case, snapshot, provider = make_provider(
        MutatingRoleProvider("cio", {"evidence_ids": ["rogue-evidence"]})
    )
    with pytest.raises(ForecastIntegrityError, match="outside the approved bundle"):
        provider.research(case, snapshot)


def test_explicit_evidence_auditor_block_halts_case() -> None:
    case, snapshot, provider = make_provider(
        MutatingRoleProvider("evidence-auditor", {"approved": False})
    )
    with pytest.raises(ForecastIntegrityError, match="auditor blocked"):
        provider.research(case, snapshot)


class MultiMutatingRoleProvider:
    network_enabled = False

    def __init__(self, updates: dict[str, dict[str, object]]) -> None:
        self.updates = updates
        self.delegate = ReplayModelProvider(
            ROOT / "data/fixtures/agent_outputs.json", "nvda-earnings-demo"
        )

    def invoke(self, role: str, model_alias: str, input_hash: str):  # type: ignore[no-untyped-def]
        result = self.delegate.invoke(role, model_alias, input_hash)
        output = {**result.output, **self.updates.get(role, {})}
        return result.model_copy(update={"output": output})


def test_downstream_roles_cannot_cite_evidence_not_approved_by_auditor() -> None:
    approved = ["demo-aapl-20240223-price"]
    model = MultiMutatingRoleProvider(
        {
            "evidence-auditor": {"evidence_ids": approved},
            "bull": {"evidence_ids": approved},
            "bear": {"evidence_ids": approved},
            "base-rate": {"evidence_ids": approved},
        }
    )
    case, snapshot, provider = make_provider(model)
    with pytest.raises(ForecastIntegrityError, match="outside the approved bundle"):
        provider.research(case, snapshot)


def test_missing_cio_forecasts_forces_abstention() -> None:
    case, snapshot, provider = make_provider(MutatingRoleProvider("cio", {"forecasts": []}))
    dossier = provider.research(case, snapshot)
    assert all(forecast.abstained for forecast in dossier.forecasts)


class SocketAttemptProvider:
    network_enabled = False

    def invoke(self, role: str, model_alias: str, input_hash: str):  # type: ignore[no-untyped-def]
        import socket

        socket.socket()
        raise AssertionError("unreachable")


def test_replay_graph_enforces_socket_denial_despite_false_self_report() -> None:
    case, snapshot, provider = make_provider(SocketAttemptProvider())
    with pytest.raises(NetworkAccessDenied):
        provider.research(case, snapshot)
