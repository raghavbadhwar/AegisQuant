"""Pinned Temporal worker-deployment configuration for M0 workflows."""

from temporalio.common import VersioningBehavior, WorkerDeploymentVersion
from temporalio.worker import WorkerDeploymentConfig

DEPLOYMENT_NAME = "aegisquant-m0"
RESEARCH_CASE_TASK_QUEUE = "aegisquant-research-case-v1"


def worker_deployment_config(build_id: str) -> WorkerDeploymentConfig:
    normalized = build_id.strip()
    if not normalized:
        raise ValueError("Temporal build_id must not be empty")
    return WorkerDeploymentConfig(
        version=WorkerDeploymentVersion(
            deployment_name=DEPLOYMENT_NAME,
            build_id=normalized,
        ),
        use_worker_versioning=True,
        default_versioning_behavior=VersioningBehavior.PINNED,
    )
