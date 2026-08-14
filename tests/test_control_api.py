import asyncio
import json
from typing import Any

import pytest
from fastapi import Response
from temporalio.api.deployment.v1 import WorkerDeploymentOptions, WorkerDeploymentVersionInfo
from temporalio.api.enums.v1 import TaskQueueType, WorkerDeploymentVersionStatus
from temporalio.api.taskqueue.v1 import PollerInfo
from temporalio.api.workflowservice.v1 import (
    DescribeTaskQueueResponse,
    DescribeWorkerDeploymentVersionResponse,
)

import aegisquant.control_api as control_api
from aegisquant.control_api import app, dependency_readiness, live, ready
from aegisquant.workflows.versioning import DURABLE_CASE_TASK_QUEUE


def test_m0_live_health_declares_safety_boundary() -> None:
    status = asyncio.run(live())
    assert status.model_dump(mode="json") == {
        "status": "ok",
        "milestone": "M0_SECURITY_KERNEL",
        "live_trading_enabled": False,
        "broker_adapter_present": False,
        "unrestricted_web_enabled": False,
    }


@pytest.mark.parametrize(
    ("dependencies", "expected_status", "expected_state"),
    [
        ({"postgresql": True, "temporal": True}, 200, "ready"),
        ({"postgresql": False, "temporal": True}, 503, "not_ready"),
        ({"postgresql": True, "temporal": False}, 503, "not_ready"),
    ],
)
def test_ready_requires_postgresql_and_temporal(
    dependencies: dict[str, bool], expected_status: int, expected_state: str
) -> None:
    response = Response()

    status = asyncio.run(ready(response, dependencies))

    assert response.status_code == expected_status
    assert status.status == expected_state
    assert status.dependencies == dependencies


def test_dependency_readiness_probes_configured_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def probe_postgresql(dsn: str) -> bool:
        seen.append(dsn)
        return True

    async def probe_temporal(target: str, namespace: str, build_id: str) -> bool:
        seen.extend((target, namespace, build_id))
        return True

    monkeypatch.setenv("AEGISQUANT_POSTGRES_DSN", "postgresql:///aegisquant")
    monkeypatch.setenv("AEGISQUANT_TEMPORAL_TARGET", "127.0.0.1:7233")
    monkeypatch.setenv("AEGISQUANT_TEMPORAL_NAMESPACE", "aegisquant")
    monkeypatch.setenv("AEGISQUANT_TEMPORAL_BUILD_ID", "candidate-build-1")
    monkeypatch.setattr(control_api, "_probe_postgresql", probe_postgresql)
    monkeypatch.setattr(control_api, "_probe_temporal", probe_temporal)

    assert asyncio.run(dependency_readiness()) == {"postgresql": True, "temporal": True}
    assert set(seen) == {
        "postgresql:///aegisquant",
        "127.0.0.1:7233",
        "aegisquant",
        "candidate-build-1",
    }


@pytest.mark.parametrize(
    ("status_value", "queue_types", "live_pollers", "expected"),
    [
        (
            WorkerDeploymentVersionStatus.WORKER_DEPLOYMENT_VERSION_STATUS_CURRENT,
            (
                TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
                TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,
            ),
            True,
            True,
        ),
        (
            WorkerDeploymentVersionStatus.WORKER_DEPLOYMENT_VERSION_STATUS_INACTIVE,
            (
                TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
                TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,
            ),
            True,
            False,
        ),
        (
            WorkerDeploymentVersionStatus.WORKER_DEPLOYMENT_VERSION_STATUS_CURRENT,
            (TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,),
            True,
            False,
        ),
        (
            WorkerDeploymentVersionStatus.WORKER_DEPLOYMENT_VERSION_STATUS_CURRENT,
            (
                TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
                TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,
            ),
            False,
            False,
        ),
    ],
)
def test_temporal_readiness_requires_active_workflow_and_activity_queues(
    status_value: int,
    queue_types: tuple[int, ...],
    live_pollers: bool,
    expected: bool,
) -> None:
    build_id = "candidate-build-1"
    deployment = DescribeWorkerDeploymentVersionResponse(
        worker_deployment_version_info=WorkerDeploymentVersionInfo(status=status_value),
        version_task_queues=[
            DescribeWorkerDeploymentVersionResponse.VersionTaskQueue(
                name=DURABLE_CASE_TASK_QUEUE,
                type=queue_type,
            )
            for queue_type in queue_types
        ],
    )
    pollers = DescribeTaskQueueResponse(
        pollers=(
            [
                PollerInfo(
                    deployment_options=WorkerDeploymentOptions(
                        deployment_name="aegisquant-m0",
                        build_id=build_id,
                    )
                )
            ]
            if live_pollers
            else []
        )
    )

    assert (
        control_api._temporal_deployment_ready(
            deployment,
            pollers,
            pollers,
            build_id=build_id,
        )
        is expected
    )


async def _asgi_get(
    path: str,
) -> tuple[int, dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("test", 1),
        "server": ("test", 80),
        "root_path": "",
    }
    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return int(start["status"]), json.loads(body)


@pytest.mark.parametrize(
    ("dependencies", "expected_status"),
    [
        ({"postgresql": True, "temporal": True}, 200),
        ({"postgresql": False, "temporal": True}, 503),
    ],
)
def test_ready_status_is_serialized_through_asgi(
    dependencies: dict[str, bool], expected_status: int
) -> None:
    app.dependency_overrides[control_api.dependency_readiness] = lambda: dependencies
    try:
        actual_status, body = asyncio.run(_asgi_get("/health/ready"))
    finally:
        app.dependency_overrides.clear()
    assert actual_status == expected_status
    assert body["dependencies"] == dependencies


def test_m0_has_no_order_submission_route() -> None:
    paths = set(app.openapi()["paths"])
    forbidden = ("execution", "broker", "order", "ingestion")
    assert not any(token in path.lower() for path in paths for token in forbidden)
    assert all(
        method == "get" for operations in app.openapi()["paths"].values() for method in operations
    )
