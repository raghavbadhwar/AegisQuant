from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from aegisquant.object_store import LocalImmutableObjectStore
from aegisquant.workflows.contracts import (
    FixtureArtifactRef,
    RegisteredEvidenceRef,
    ResearchCaseWorkflowInput,
    SnapshotRef,
)
from aegisquant.workflows.research_case import ResearchCaseWorkflow

D = "sha256:" + "a" * 64


@activity.defn(name="freeze_fixture_snapshot_v1")
async def freeze_fixture_snapshot(command: ResearchCaseWorkflowInput) -> SnapshotRef:
    return SnapshotRef(
        tenant_id=command.tenant_id,
        snapshot_id=command.data_snapshot_id,
        manifest_digest=D,
    )


@activity.defn(name="register_fixture_evidence_v1")
async def register_fixture_evidence(
    command: ResearchCaseWorkflowInput,
) -> RegisteredEvidenceRef:
    return RegisteredEvidenceRef(
        tenant_id=command.tenant_id,
        evidence_id=uuid5(
            NAMESPACE_URL, f"{command.tenant_id}:{command.fixture_evidence.content_digest}"
        ),
        evidence_digest=command.fixture_evidence.content_digest,
    )


@activity.defn(name="emit_fixture_artifact_v1")
async def emit_fixture_artifact(command: ResearchCaseWorkflowInput) -> FixtureArtifactRef:
    return FixtureArtifactRef(
        tenant_id=command.tenant_id,
        artifact_id=uuid5(NAMESPACE_URL, f"{command.case_id}:fixture-artifact"),
        artifact_digest=D,
    )


@pytest.mark.asyncio
async def test_temporal_fixture_workflow_is_typed_and_reference_only(tmp_path: Path) -> None:
    store = LocalImmutableObjectStore(tmp_path)
    blob = store.put_if_absent(
        tenant_id="tenant-a",
        data=b"approved immutable fixture",
        media_type="text/plain",
        retention_class="test",
    )
    command = ResearchCaseWorkflowInput(
        tenant_id="tenant-a",
        case_id=uuid4(),
        data_snapshot_id="fixture-snapshot-1",
        fixture_evidence=blob,
    )
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        async with Worker(
            env.client,
            task_queue="m0-fixture-test",
            workflows=[ResearchCaseWorkflow],
            activities=[freeze_fixture_snapshot, register_fixture_evidence, emit_fixture_artifact],
        ):
            result = await env.client.execute_workflow(
                ResearchCaseWorkflow.run,
                command,
                id=f"test-{command.case_id}",
                task_queue="m0-fixture-test",
                result_type=None,
            )
    assert result.tenant_id == "tenant-a"
    assert result.case_id == command.case_id
    assert result.evidence.evidence_digest == blob.content_digest
