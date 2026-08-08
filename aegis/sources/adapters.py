"""Narrow optional live-source adapters; no arbitrary command surface."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

from aegis.contracts import FetchedDocument, ScrapeJob, SourceManifest, SourceRequest


class ConnectorUnavailable(RuntimeError):
    pass


def _check_url(url: str, manifest: SourceManifest) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(
        host == domain.lower() or host.endswith(f".{domain.lower()}") for domain in manifest.domains
    ):
        raise ValueError("URL is outside the HTTPS source allowlist")


class DirectHTTPConnector:
    version = "direct-http-v1"

    def __init__(self, url_builder: Callable[[SourceRequest, SourceManifest], str]) -> None:
        self.url_builder = url_builder

    def fetch(
        self, request: SourceRequest, manifest: SourceManifest, request_id: str
    ) -> FetchedDocument:
        if request.mode != "live_research":
            raise ValueError("direct HTTP is live-research only")
        url = self.url_builder(request, manifest)
        _check_url(url, manifest)
        try:
            import httpx
        except ImportError as exc:
            raise ConnectorUnavailable("install the live extra for direct HTTP") from exc
        response = httpx.get(
            url,
            follow_redirects=False,
            timeout=20.0,
            headers={"User-Agent": "AegisQuant/0.1 research@example.invalid"},
        )
        if response.is_redirect:
            raise ValueError("redirects require explicit allowlist revalidation")
        response.raise_for_status()
        if len(response.content) > 5_000_000:
            raise ValueError("source response exceeds the body limit")
        return FetchedDocument(
            source_id=manifest.source_id,
            request_id=request_id,
            url=url,
            connector="direct-http",
            connector_version=self.version,
            status_code=response.status_code,
            headers={key.lower(): value for key, value in response.headers.items()},
            body=response.content,
            fetched_at=datetime.now().astimezone(),
            media_type=response.headers.get("content-type", "application/octet-stream"),
        )


class AgentReachConnector:
    """Fixed operation wrappers around Agent Reach; never accepts raw argv or shell text."""

    version = "agent-reach-v1"
    _OPERATIONS: ClassVar[dict[str, str]] = {
        "reddit": "search_reddit",
        "x": "search_x",
        "youtube": "get_youtube_transcript",
        "github": "search_github_activity",
        "rss": "read_rss",
    }

    def __init__(self, operation: str) -> None:
        try:
            self.operation = self._OPERATIONS[operation]
        except KeyError as exc:
            raise ValueError("unsupported Agent Reach operation") from exc

    def fetch(
        self, request: SourceRequest, manifest: SourceManifest, request_id: str
    ) -> FetchedDocument:
        if request.mode != "live_research":
            raise ValueError("Agent Reach is live-research only")
        executable = shutil.which("agent-reach-search")
        if executable is None:
            raise ConnectorUnavailable("agent-reach-search executable is unavailable")
        argv = [
            executable,
            f"{self.operation}: {request.query}",
            "--limit",
            str(min(request.max_sources, 10)),
        ]
        completed = subprocess.run(
            argv,
            shell=False,
            check=True,
            capture_output=True,
            timeout=30,
            env={"PATH": f"{Path(executable).parent}:/usr/bin:/bin"},
        )
        body = completed.stdout[:1_000_000]
        return FetchedDocument(
            source_id=manifest.source_id,
            request_id=request_id,
            url=f"https://agent-reach.invalid/{self.operation}",
            connector="agent-reach",
            connector_version=self.version,
            status_code=200,
            headers={"content-type": "text/plain"},
            body=body,
            fetched_at=datetime.now().astimezone(),
            media_type="text/plain",
        )


class ScraplingWorkerBoundary:
    """Manifest-bound JSON boundary for an isolated live-research worker."""

    def build_payload(self, job: ScrapeJob, manifest: SourceManifest) -> bytes:
        if (
            job.product_mode != "live_research"
            or not manifest.live_safe
            or not manifest.obey_robots
        ):
            raise ValueError("Scrapling job is not authorized for live research")
        if job.source_id != manifest.source_id:
            raise ValueError("Scrapling job source does not match its manifest")
        if not set(job.domain_allowlist).issubset(manifest.domains):
            raise ValueError("Scrapling allowlist exceeds manifest domains")
        if job.maximum_pages > manifest.max_pages_per_job:
            raise ValueError("Scrapling page limit exceeds source manifest")
        if job.maximum_depth > manifest.max_depth:
            raise ValueError("Scrapling depth exceeds source manifest")
        if job.timeout_seconds > 60:
            raise ValueError("Scrapling timeout exceeds worker policy")
        return json.dumps(job.model_dump(mode="json"), sort_keys=True).encode()

    def parse_result(self, payload: bytes) -> dict[str, Any]:
        result = json.loads(payload)
        if not isinstance(result, dict) or not isinstance(result.get("body"), str):
            raise ValueError("invalid Scrapling worker response")
        return result
