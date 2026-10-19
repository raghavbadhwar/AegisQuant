#!/usr/bin/env python3
"""Explicitly capture the fixed M0 Temporal golden history."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import temporalio
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from aegisquant.case_ledger.postgres import digest_jsonb
from aegisquant.contracts.artifact import BlobRef
from aegisquant.contracts.research import ResearchManifest
from aegisquant.fixture_case import FixtureCaseSpec
from aegisquant.security.digests import digest_canonical
from aegisquant.workflows.contracts import (
    DurableExecutionWorkflowRef,
    DurableOfflineCaseWorkflowInput,
    DurablePreparedRef,
    DurableReconciliationRef,
    ReconcileDurableCaseInput,
    ReproducibleResearchWorkflowInput,
    ResearchCaseWorkflowInput,
)
from aegisquant.workflows.durable_case import DurableOfflineCaseWorkflow
from aegisquant.workflows.fixture_activities import FIXTURE_ACTIVITIES
from aegisquant.workflows.reproducible_activities import REPRODUCIBLE_ACTIVITIES
from aegisquant.workflows.research_case import ResearchCaseWorkflow
from aegisquant.workflows.research_case_v2 import ReproducibleResearchCaseWorkflow
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
V2_WORKFLOW_ID = "m1-golden-research-case-v2"
V2_BUILD_ID = "m1-golden-v2"
V2_OUTPUT = Path("tests/fixtures/temporal/research_case_workflow_v2.json")
DURABLE_WORKFLOW_ID = "m2-golden-durable-offline-case-v1"
DURABLE_BUILD_ID = "m2-golden-durable-v1"
DURABLE_OUTPUT = Path("tests/fixtures/temporal/durable_offline_case_workflow_v1.json")
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


def fixed_v2_command() -> ReproducibleResearchWorkflowInput:
    case_id = UUID("00000000-0000-0000-0000-000000000102")
    evidence = BlobRef(
        tenant_id="tenant-a",
        uri="fixture://approved/research-case-v2",
        content_digest=FIXTURE_DIGEST,
        size_bytes=26,
        media_type="application/json",
        retention_class="golden-history",
    )
    return ReproducibleResearchWorkflowInput(
        tenant_id="tenant-a",
        case_id=case_id,
        manifest=ResearchManifest(
            tenant_id="tenant-a",
            case_id=case_id,
            snapshot_id="fixture-snapshot-v2",
            snapshot_manifest_digest=FIXTURE_DIGEST,
            snapshot_content_digest=FIXTURE_DIGEST,
            data_manifest_digests=(FIXTURE_DIGEST,),
            rights_manifest_ids=("fixture-rights-v1",),
            frozen_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        fixture_evidence=evidence,
    )


def fixed_durable_command() -> DurableOfflineCaseWorkflowInput:
    spec = FixtureCaseSpec.model_validate_json(
        Path("data/fixtures/cases/multi_asset_control.json").read_bytes()
    )
    fixture_digest = digest_canonical(spec)
    account_payload = {
        "tenant_id": spec.manifest.tenant_id,
        "case_id": str(spec.manifest.case_id),
        "account_id": "fixture-paper-account",
        "cash": str(spec.initial_cash),
        "positions": [],
        "state_sequence": 0,
    }
    return DurableOfflineCaseWorkflowInput(
        tenant_id=spec.manifest.tenant_id,
        case_id=spec.manifest.case_id,
        account_id="fixture-paper-account",
        fixture_name="multi_asset_control.json",
        fixture_spec_digest=fixture_digest,
        initial_account_digest=digest_jsonb(account_payload),
        execution_id=uuid5(NAMESPACE_URL, f"aegisquant:durable-execution:{fixture_digest}"),
    )


@activity.defn(name="prepare_durable_case_v1")
async def fixed_durable_prepare(
    command: DurableOfflineCaseWorkflowInput,
) -> DurablePreparedRef:
    return DurablePreparedRef(
        tenant_id=command.tenant_id,
        case_id=command.case_id,
        account_id=command.account_id,
        state_sequence=0,
        snapshot_digest=command.initial_account_digest,
    )


@activity.defn(name="execute_durable_case_v1")
async def fixed_durable_execute(
    command: DurableOfflineCaseWorkflowInput,
) -> DurableExecutionWorkflowRef:
    return DurableExecutionWorkflowRef(
        tenant_id=command.tenant_id,
        case_id=command.case_id,
        account_id=command.account_id,
        execution_id=command.execution_id,
        nonce="0123456789abcdef0123456789abcdef",
        decision_digest="sha256:" + "e" * 64,
        request_digest=command.fixture_spec_digest,
        result_digest="sha256:" + "b" * 64,
        account_state_sequence=1,
        account_snapshot_digest="sha256:" + "c" * 64,
        fill_digests=("sha256:" + "d" * 64,),
    )


@activity.defn(name="reconcile_durable_case_v1")
async def fixed_durable_reconcile(
    value: ReconcileDurableCaseInput,
) -> DurableReconciliationRef:
    return DurableReconciliationRef(
        tenant_id=value.command.tenant_id,
        case_id=value.command.case_id,
        account_id=value.command.account_id,
        execution_id=value.command.execution_id,
        result_digest=value.execution.result_digest,
        account_snapshot_digest=value.execution.account_snapshot_digest,
        fill_digests=value.execution.fill_digests,
        reconciled=True,
    )


DURABLE_CAPTURE_ACTIVITIES = (
    fixed_durable_prepare,
    fixed_durable_execute,
    fixed_durable_reconcile,
)


async def capture(output: Path, version: str) -> int:
    workflow_class: Any = ResearchCaseWorkflow
    activities = FIXTURE_ACTIVITIES
    command: (
        ResearchCaseWorkflowInput
        | ReproducibleResearchWorkflowInput
        | DurableOfflineCaseWorkflowInput
    ) = fixed_command()
    workflow_id = WORKFLOW_ID
    build_id = BUILD_ID
    task_queue = RESEARCH_CASE_TASK_QUEUE
    if version == "v2":
        workflow_class = ReproducibleResearchCaseWorkflow
        activities = REPRODUCIBLE_ACTIVITIES
        command = fixed_v2_command()
        workflow_id = V2_WORKFLOW_ID
        build_id = V2_BUILD_ID
        task_queue = "m1-golden-research-case-v2"
    elif version == "durable":
        workflow_class = DurableOfflineCaseWorkflow
        activities = DURABLE_CAPTURE_ACTIVITIES
        command = fixed_durable_command()
        workflow_id = DURABLE_WORKFLOW_ID
        build_id = DURABLE_BUILD_ID
        task_queue = "m2-golden-durable-offline-case-v1"
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[workflow_class],
            activities=activities,
            deployment_config=worker_deployment_config(build_id),
        ):
            handle = await environment.client.start_workflow(
                workflow_class.run,
                command,
                id=workflow_id,
                task_queue=task_queue,
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
    parser.add_argument("--version", choices=("v1", "v2", "durable"), default="v1")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--accept",
        action="store_true",
        help="required acknowledgement before writing/replacing the golden fixture",
    )
    args = parser.parse_args()
    if not args.accept:
        parser.error("--accept is required; review and commit history changes explicitly")
    output = args.output or (
        V2_OUTPUT
        if args.version == "v2"
        else DURABLE_OUTPUT
        if args.version == "durable"
        else DEFAULT_OUTPUT
    )
    count = asyncio.run(capture(output, args.version))
    print(f"captured {count} events with temporalio {temporalio.__version__} to {output}")


if __name__ == "__main__":
    main()
