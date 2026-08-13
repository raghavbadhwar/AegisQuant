#!/usr/bin/env python3
"""Explicitly capture the fixed M0 Temporal golden history."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import UUID

import temporalio
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from aegisquant.contracts.artifact import BlobRef
from aegisquant.workflows.contracts import ResearchCaseWorkflowInput
from aegisquant.workflows.fixture_activities import FIXTURE_ACTIVITIES
from aegisquant.workflows.research_case import ResearchCaseWorkflow
from aegisquant.workflows.start_policy import (
    RESEARCH_CASE_ID_CONFLICT_POLICY,
    RESEARCH_CASE_ID_REUSE_POLICY,
)
from aegisquant.workflows.versioning import (
    RESEARCH_CASE_TASK_QUEUE,
    worker_deployment_config,
)

WORKFLOW_ID = "m0-golden-research-case-v1"
BUILD_ID = "m0-golden-v1"
DEFAULT_OUTPUT = Path("tests/fixtures/temporal/research_case_workflow_v1.json")
FIXTURE_DIGEST = "sha256:" + "a" * 64


def fixed_command() -> ResearchCaseWorkflowInput:
    return ResearchCaseWorkflowInput(
        tenant_id="tenant-a",
        case_id=UUID("00000000-0000-0000-0000-000000000101"),
        data_snapshot_id="fixture-snapshot-v1",
        fixture_evidence=BlobRef(
            tenant_id="tenant-a",
            uri="fixture://approved/research-case-v1",
            content_digest=FIXTURE_DIGEST,
            size_bytes=26,
            media_type="text/plain",
            retention_class="golden-history",
        ),
    )


async def capture(output: Path) -> int:
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as environment:
        async with Worker(
            environment.client,
            task_queue=RESEARCH_CASE_TASK_QUEUE,
            workflows=[ResearchCaseWorkflow],
            activities=FIXTURE_ACTIVITIES,
            deployment_config=worker_deployment_config(BUILD_ID),
        ):
            handle = await environment.client.start_workflow(
                ResearchCaseWorkflow.run,
                fixed_command(),
                id=WORKFLOW_ID,
                task_queue=RESEARCH_CASE_TASK_QUEUE,
                id_reuse_policy=RESEARCH_CASE_ID_REUSE_POLICY,
                id_conflict_policy=RESEARCH_CASE_ID_CONFLICT_POLICY,
            )
            await handle.result()
            history = await handle.fetch_history()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(history.to_json() + "\n")
    return len(history.events)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--accept",
        action="store_true",
        help="required acknowledgement before writing/replacing the golden fixture",
    )
    args = parser.parse_args()
    if not args.accept:
        parser.error("--accept is required; review and commit history changes explicitly")
    count = asyncio.run(capture(args.output))
    print(f"captured {count} events with temporalio {temporalio.__version__} to {args.output}")


if __name__ == "__main__":
    main()
