from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegis.contracts import FetchedDocument, ScrapeJob, SourceRequest
from aegis.sources import RawStore, SourceGateway, SourcePlanner, SourcePolicyDenied, SourceRegistry
from aegis.sources.adapters import AgentReachConnector

ROOT = Path(__file__).resolve().parents[2]


class CountingConnector:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, request, manifest, request_id):  # type: ignore[no-untyped-def]
        self.calls += 1
        return FetchedDocument(
            source_id=manifest.source_id,
            request_id=request_id,
            url="https://investor.apple.com/demo",
            connector="counting",
            connector_version="1",
            status_code=200,
            body=b"should not be fetched",
            fetched_at=request.as_of,
            media_type="text/plain",
        )


def test_historical_source_request_is_denied_before_connector(tmp_path: Path) -> None:
    registry = SourceRegistry.load(ROOT / "configs/sources")
    connector = CountingConnector()
    gateway = SourceGateway(
        registry, SourcePlanner(registry), RawStore(tmp_path), {"direct-http": connector}
    )
    request = SourceRequest(
        case_id="historical-denial",
        entity_ids=["AAPL"],
        information_type="company_announcement",
        query="current web data must be denied",
        as_of=datetime(2024, 2, 23, tzinfo=UTC),
        mode="historical",
        max_sources=1,
        max_cost_usd=0.0,
    )
    with pytest.raises(SourcePolicyDenied, match="forbidden in historical"):
        gateway.acquire(request)
    assert connector.calls == 0
    assert list(tmp_path.iterdir()) == []


def test_scrape_job_rejects_ssrf_and_non_allowlisted_urls() -> None:
    common = dict(
        job_id="job",
        source_id="source",
        purpose="test",
        extraction_schema="article-v1",
        mode="static",
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        domain_allowlist=["example.com"],
        maximum_pages=1,
        maximum_depth=0,
        timeout_seconds=10,
    )
    with pytest.raises(ValueError, match="outside the domain allowlist"):
        ScrapeJob(url="http://169.254.169.254/latest/meta-data", **common)
    with pytest.raises(ValueError, match="outside the domain allowlist"):
        ScrapeJob(url="file:///etc/passwd", **common)


def test_agent_reach_wrapper_uses_fixed_argv_no_shell_or_secret_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    registry = SourceRegistry.load(ROOT / "configs/sources")
    manifest = registry.get("agent-reach-github")
    request = SourceRequest(
        case_id="reach",
        entity_ids=["repo"],
        information_type="github_activity",
        query="org/repo releases",
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        mode="live_research",
        max_sources=1,
        max_cost_usd=0.0,
    )
    captured = {}

    class Result:
        stdout = b"typed result"

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        captured["argv"] = argv
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr("aegis.sources.adapters.subprocess.run", fake_run)
    fetched = AgentReachConnector("github").fetch(request, manifest, "request-id")
    assert fetched.body == b"typed result"
    assert captured["shell"] is False
    assert captured["argv"][0] == "agent-reach-search"
    assert captured["argv"][1].startswith("search_github_activity:")
    assert set(captured["env"]) == {"PATH"}


class FailingRawStore:
    def commit(self, fetched):  # type: ignore[no-untyped-def]
        raise RuntimeError("raw commit failed")


def test_raw_store_failure_prevents_normalization(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    del tmp_path
    registry = SourceRegistry.load(ROOT / "configs/sources")
    connector = CountingConnector()
    parsed = False

    def forbidden_normalize(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal parsed
        parsed = True
        raise AssertionError("normalizer ran before raw commit")

    monkeypatch.setattr("aegis.sources.pipeline.normalize", forbidden_normalize)
    gateway = SourceGateway(
        registry,
        SourcePlanner(registry),
        FailingRawStore(),  # type: ignore[arg-type]
        {"direct-http": connector},
    )
    request = SourceRequest(
        case_id="raw-first",
        entity_ids=["AAPL"],
        information_type="company_announcement",
        query="raw first",
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        mode="live_research",
        max_sources=1,
        max_cost_usd=0.0,
    )
    with pytest.raises(RuntimeError, match="raw commit failed"):
        gateway.acquire(request)
    assert connector.calls == 1
    assert not parsed
