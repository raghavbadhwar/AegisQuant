"""Thin control-plane API; M0 intentionally exposes no execution path."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, Response, status
from pydantic import BaseModel, ConfigDict
from temporalio.api.deployment.v1 import WorkerDeploymentVersion
from temporalio.api.enums.v1 import TaskQueueType, WorkerDeploymentVersionStatus
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import (
    DescribeNamespaceRequest,
    DescribeTaskQueueRequest,
    DescribeTaskQueueResponse,
    DescribeWorkerDeploymentVersionRequest,
    DescribeWorkerDeploymentVersionResponse,
)
from temporalio.client import Client

from aegisquant.workflows.versioning import DEPLOYMENT_NAME, DURABLE_CASE_TASK_QUEUE


class HealthStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["ok"] = "ok"
    milestone: Literal["M0_SECURITY_KERNEL"] = "M0_SECURITY_KERNEL"
    live_trading_enabled: Literal[False] = False
    broker_adapter_present: Literal[False] = False
    unrestricted_web_enabled: Literal[False] = False


class ReadinessStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["ready", "not_ready"]
    dependencies: dict[Literal["postgresql", "temporal"], bool]
    live_trading_enabled: Literal[False] = False
    broker_adapter_present: Literal[False] = False
    unrestricted_web_enabled: Literal[False] = False


def _probe_postgresql(dsn: str) -> bool:
    try:
        with psycopg.connect(dsn, connect_timeout=2) as connection:
            row = connection.execute(
                """
                SELECT
                    aq_current_tenant_id(),
                    to_regprocedure(
                        'aq_prepare_paper_account(text,uuid,text,bigint,text,jsonb)'
                    ) IS NOT NULL,
                    to_regprocedure(
                        'aq_record_paper_execution('
                        'text,uuid,text,uuid,text,text,text,text,text,jsonb,bigint,text,jsonb)'
                    ) IS NOT NULL,
                    to_regprocedure(
                        'aq_record_execution_reconciliation(text,uuid,text,uuid,text)'
                    ) IS NOT NULL,
                    has_table_privilege(
                        current_user, 'paper_account_snapshots', 'SELECT'
                    ),
                    has_table_privilege(
                        current_user, 'paper_execution_results', 'SELECT'
                    ),
                    has_function_privilege(
                        current_user,
                        to_regprocedure(
                            'aq_prepare_paper_account(text,uuid,text,bigint,text,jsonb)'
                        ),
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        current_user,
                        to_regprocedure(
                            'aq_record_paper_execution('
                            'text,uuid,text,uuid,text,text,text,text,text,jsonb,bigint,text,jsonb)'
                        ),
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        current_user,
                        to_regprocedure(
                            'aq_record_execution_reconciliation(text,uuid,text,uuid,text)'
                        ),
                        'EXECUTE'
                    )
                """
            ).fetchone()
            return row is not None and bool(row[0]) and all(row[1:])
    except (OSError, ValueError, psycopg.Error):
        return False


async def _probe_temporal(target: str, namespace: str, build_id: str) -> bool:
    try:
        client = await Client.connect(target, namespace=namespace, lazy=True)
        timeout = timedelta(seconds=2)
        if not await client.service_client.check_health(timeout=timeout):
            return False
        service = client.service_client.workflow_service
        await service.describe_namespace(
            DescribeNamespaceRequest(namespace=namespace), timeout=timeout
        )
        deployment = await service.describe_worker_deployment_version(
            DescribeWorkerDeploymentVersionRequest(
                namespace=namespace,
                deployment_version=WorkerDeploymentVersion(
                    deployment_name=DEPLOYMENT_NAME,
                    build_id=build_id,
                ),
                report_task_queue_stats=True,
            ),
            timeout=timeout,
        )
        workflow_pollers, activity_pollers = await asyncio.gather(
            service.describe_task_queue(
                DescribeTaskQueueRequest(
                    namespace=namespace,
                    task_queue=TaskQueue(name=DURABLE_CASE_TASK_QUEUE),
                    task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
                    report_pollers=True,
                ),
                timeout=timeout,
            ),
            service.describe_task_queue(
                DescribeTaskQueueRequest(
                    namespace=namespace,
                    task_queue=TaskQueue(name=DURABLE_CASE_TASK_QUEUE),
                    task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,
                    report_pollers=True,
                ),
                timeout=timeout,
            ),
        )
        return _temporal_deployment_ready(
            deployment,
            workflow_pollers,
            activity_pollers,
            build_id=build_id,
        )
    except Exception:
        return False


def _temporal_deployment_ready(
    deployment: DescribeWorkerDeploymentVersionResponse,
    workflow_pollers: DescribeTaskQueueResponse,
    activity_pollers: DescribeTaskQueueResponse,
    *,
    build_id: str,
) -> bool:
    eligible_statuses = {
        WorkerDeploymentVersionStatus.WORKER_DEPLOYMENT_VERSION_STATUS_CURRENT,
        WorkerDeploymentVersionStatus.WORKER_DEPLOYMENT_VERSION_STATUS_RAMPING,
    }
    queue_types = {
        queue.type
        for queue in deployment.version_task_queues
        if queue.name == DURABLE_CASE_TASK_QUEUE
    }

    def has_live_poller(response: DescribeTaskQueueResponse) -> bool:
        return any(
            poller.deployment_options.deployment_name == DEPLOYMENT_NAME
            and poller.deployment_options.build_id == build_id
            for poller in response.pollers
        )

    return (
        deployment.worker_deployment_version_info.status in eligible_statuses
        and TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW in queue_types
        and TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY in queue_types
        and has_live_poller(workflow_pollers)
        and has_live_poller(activity_pollers)
    )


async def dependency_readiness() -> dict[Literal["postgresql", "temporal"], bool]:
    postgres_dsn = os.environ.get("AEGISQUANT_POSTGRES_DSN")
    temporal_target = os.environ.get("AEGISQUANT_TEMPORAL_TARGET")
    temporal_namespace = os.environ.get("AEGISQUANT_TEMPORAL_NAMESPACE")
    temporal_build_id = os.environ.get("AEGISQUANT_TEMPORAL_BUILD_ID")
    temporal_probe = (
        _probe_temporal(temporal_target, temporal_namespace, temporal_build_id)
        if temporal_target and temporal_namespace and temporal_build_id
        else _false()
    )
    postgresql, temporal = await asyncio.gather(
        asyncio.to_thread(_probe_postgresql, postgres_dsn) if postgres_dsn else _false(),
        temporal_probe,
    )
    return {"postgresql": postgresql, "temporal": temporal}


async def _false() -> bool:
    return False


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # External clients are initialized here only after their milestones pass.
    yield


app = FastAPI(
    title="AegisQuant Control API",
    version="0.1.0",
    lifespan=lifespan,
    description="M0 fixture-only control plane; no broker or execution endpoints.",
)


@app.get("/health/live", response_model=HealthStatus)
async def live() -> HealthStatus:
    return HealthStatus()


@app.get(
    "/health/ready",
    response_model=ReadinessStatus,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessStatus}},
)
async def ready(
    response: Response,
    dependencies: Annotated[
        dict[Literal["postgresql", "temporal"], bool], Depends(dependency_readiness)
    ],
) -> ReadinessStatus:
    is_ready = dependencies == {"postgresql": True, "temporal": True}
    response.status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessStatus(
        status="ready" if is_ready else "not_ready",
        dependencies=dependencies,
    )
