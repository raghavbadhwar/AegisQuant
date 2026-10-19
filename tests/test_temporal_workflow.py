import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from aegisquant.contracts.research import ResearchManifest
from aegisquant.object_store import LocalImmutableObjectStore
from aegisquant.security.digests import digest_canonical
from aegisquant.workflows.contracts import (
    EmitFixtureArtifactInput,
    FixtureArtifactRef,
    RegisteredEvidenceRef,
    RegisterFixtureEvidenceInput,
    ReproducibleResearchWorkflowInput,
    ResearchCaseWorkflowInput,
    SnapshotRef,
)
from aegisquant.workflows.fixture_activities import FIXTURE_ACTIVITIES
from aegisquant.workflows.reproducible_activities import REPRODUCIBLE_ACTIVITIES
from aegisquant.workflows.research_case import ResearchCaseWorkflow
from aegisquant.workflows.research_case_v2 import ReproducibleResearchCaseWorkflow
from aegisquant.workflows.start_policy import (
    RESEARCH_CASE_ID_CONFLICT_POLICY,
    RESEARCH_CASE_ID_REUSE_POLICY,
    research_case_workflow_id,
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
            activities=FIXTURE_ACTIVITIES,
        ):
            result = await env.client.execute_workflow(
                ResearchCaseWorkflow.run,
                command,
                id=research_case_workflow_id(command.tenant_id, command.case_id),
                task_queue="m0-fixture-test",
                id_reuse_policy=RESEARCH_CASE_ID_REUSE_POLICY,
                id_conflict_policy=RESEARCH_CASE_ID_CONFLICT_POLICY,
                result_type=None,
            )
    assert result.tenant_id == "tenant-a"
    assert result.case_id == command.case_id
    assert result.evidence.source_content_digest == blob.content_digest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bad_step", "expected_calls"),
    [
        ("snapshot", ["snapshot"]),
        ("evidence", ["snapshot", "evidence"]),
        ("artifact", ["snapshot", "evidence", "artifact"]),
    ],
)
async def test_cross_tenant_activity_result_stops_before_later_steps(
    bad_step: str, expected_calls: list[str], tmp_path: Path
) -> None:
    calls: list[str] = []
    digest = "sha256:" + "d" * 64

    @activity.defn(name="freeze_fixture_snapshot_v1")
    async def snapshot_activity(value: ResearchCaseWorkflowInput) -> SnapshotRef:
        calls.append("snapshot")
        return SnapshotRef(
            tenant_id="tenant-b" if bad_step == "snapshot" else value.tenant_id,
            snapshot_id=value.data_snapshot_id,
            manifest_digest=digest,
        )

    @activity.defn(name="register_fixture_evidence_v1")
    async def evidence_activity(
        value: RegisterFixtureEvidenceInput,
    ) -> RegisteredEvidenceRef:
        calls.append("evidence")
        return RegisteredEvidenceRef(
            tenant_id="tenant-b" if bad_step == "evidence" else value.tenant_id,
            case_id=value.case_id,
            evidence_id=uuid4(),
            source_content_digest=value.fixture_evidence.content_digest,
            evidence_digest=digest,
        )

    @activity.defn(name="emit_fixture_artifact_v1")
    async def artifact_activity(value: EmitFixtureArtifactInput) -> FixtureArtifactRef:
        calls.append("artifact")
        return FixtureArtifactRef(
            tenant_id="tenant-b" if bad_step == "artifact" else value.tenant_id,
            case_id=value.case_id,
            snapshot_id=value.snapshot.snapshot_id,
            evidence_digest=value.evidence.evidence_digest,
            artifact_id=uuid4(),
            artifact_digest=digest,
        )

    value = ResearchCaseWorkflowInput(
        tenant_id="tenant-a",
        case_id=uuid4(),
        data_snapshot_id="fixture-snapshot-1",
        fixture_evidence=LocalImmutableObjectStore(tmp_path / bad_step).put_if_absent(
            tenant_id="tenant-a",
            data=b"approved fixture",
            media_type="text/plain",
            retention_class="test",
        ),
    )
    task_queue = f"m0-tenant-stop-{bad_step}"
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ResearchCaseWorkflow],
            activities=[snapshot_activity, evidence_activity, artifact_activity],
        ):
            with pytest.raises(WorkflowFailureError):
                await environment.client.execute_workflow(
                    ResearchCaseWorkflow.run,
                    value,
                    id=research_case_workflow_id(value.tenant_id, value.case_id),
                    task_queue=task_queue,
                    id_reuse_policy=RESEARCH_CASE_ID_REUSE_POLICY,
                    id_conflict_policy=RESEARCH_CASE_ID_CONFLICT_POLICY,
                )
    assert calls == expected_calls


@pytest.mark.asyncio
async def test_workflow_cancellation_waits_for_activity_and_stops_downstream(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    downstream_calls: list[str] = []

    @activity.defn(name="freeze_fixture_snapshot_v1")
    async def blocking_snapshot(value: ResearchCaseWorkflowInput) -> SnapshotRef:
        del value
        started.set()
        try:
            while True:
                activity.heartbeat()
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("unreachable")

    @activity.defn(name="register_fixture_evidence_v1")
    async def unexpected_evidence(
        value: RegisterFixtureEvidenceInput,
    ) -> RegisteredEvidenceRef:
        del value
        downstream_calls.append("evidence")
        raise AssertionError("downstream evidence activity must not run")

    @activity.defn(name="emit_fixture_artifact_v1")
    async def unexpected_artifact(value: EmitFixtureArtifactInput) -> FixtureArtifactRef:
        del value
        downstream_calls.append("artifact")
        raise AssertionError("downstream artifact activity must not run")

    value = ResearchCaseWorkflowInput(
        tenant_id="tenant-a",
        case_id=uuid4(),
        data_snapshot_id="fixture-snapshot-1",
        fixture_evidence=LocalImmutableObjectStore(tmp_path).put_if_absent(
            tenant_id="tenant-a",
            data=b"approved fixture",
            media_type="text/plain",
            retention_class="test",
        ),
    )
    task_queue = "m0-cancellation-wait"
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ResearchCaseWorkflow],
            activities=[blocking_snapshot, unexpected_evidence, unexpected_artifact],
        ):
            handle = await environment.client.start_workflow(
                ResearchCaseWorkflow.run,
                value,
                id=research_case_workflow_id(value.tenant_id, value.case_id),
                task_queue=task_queue,
                id_reuse_policy=RESEARCH_CASE_ID_REUSE_POLICY,
                id_conflict_policy=RESEARCH_CASE_ID_CONFLICT_POLICY,
            )
            await asyncio.wait_for(started.wait(), timeout=5)
            await handle.cancel()
            with pytest.raises(WorkflowFailureError):
                await handle.result()
    assert cancelled.is_set()
    assert downstream_calls == []


def test_workflow_identity_is_tenant_bound() -> None:
    case_id = uuid4()
    tenant_a = research_case_workflow_id("tenant-a", case_id)
    tenant_b = research_case_workflow_id("tenant-b", case_id)
    assert tenant_a != tenant_b
    assert str(case_id) in tenant_a
    with pytest.raises(ValueError, match="tenant_id"):
        research_case_workflow_id("   ", case_id)


@pytest.mark.asyncio
async def test_v2_workflow_replays_only_frozen_manifest_references(tmp_path: Path) -> None:
    store = LocalImmutableObjectStore(tmp_path)
    blob = store.put_if_absent(
        tenant_id="tenant-a",
        data=b"frozen multi-asset fixture",
        media_type="application/json",
        retention_class="test",
    )
    case_id = uuid4()
    manifest = ResearchManifest(
        tenant_id="tenant-a",
        case_id=case_id,
        snapshot_id="multi-asset-v1",
        snapshot_manifest_digest="sha256:" + "a" * 64,
        snapshot_content_digest=blob.content_digest,
        data_manifest_digests=(blob.content_digest,),
        rights_manifest_ids=("fixture-rights-v1",),
        frozen_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    command = ReproducibleResearchWorkflowInput(
        tenant_id="tenant-a", case_id=case_id, manifest=manifest, fixture_evidence=blob
    )
    assert (
        ReproducibleResearchWorkflowInput.model_validate_json(command.model_dump_json()) == command
    )
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        async with Worker(
            env.client,
            task_queue="m1-reproducible-test",
            workflows=[ReproducibleResearchCaseWorkflow],
            activities=REPRODUCIBLE_ACTIVITIES,
        ):
            handle = await env.client.start_workflow(
                ReproducibleResearchCaseWorkflow.run,
                command,
                id=research_case_workflow_id(command.tenant_id, command.case_id),
                task_queue="m1-reproducible-test",
            )
            result = await handle.result()
            history = await handle.fetch_history()
    assert result.tenant_id == command.tenant_id
    assert result.research_manifest_digest.startswith("sha256:")
    replay = await Replayer(
        workflows=[ReproducibleResearchCaseWorkflow], data_converter=pydantic_data_converter
    ).replay_workflow(history)
    assert replay.replay_failure is None


@pytest.mark.asyncio
async def test_v2_workflow_rejects_incoherent_artifact_activity_result(tmp_path: Path) -> None:
    store = LocalImmutableObjectStore(tmp_path)
    blob = store.put_if_absent(
        tenant_id="tenant-a",
        data=b"frozen multi-asset fixture",
        media_type="application/json",
        retention_class="test",
    )
    case_id = uuid4()
    manifest = ResearchManifest(
        tenant_id="tenant-a",
        case_id=case_id,
        snapshot_id="multi-asset-v1",
        snapshot_manifest_digest="sha256:" + "a" * 64,
        snapshot_content_digest=blob.content_digest,
        data_manifest_digests=(blob.content_digest,),
        rights_manifest_ids=("fixture-rights-v1",),
        frozen_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    command = ReproducibleResearchWorkflowInput(
        tenant_id="tenant-a", case_id=case_id, manifest=manifest, fixture_evidence=blob
    )

    @activity.defn(name="verify_reproducible_manifest_v1")
    async def manifest_activity(value: ReproducibleResearchWorkflowInput) -> str:
        return digest_canonical(value.manifest)

    @activity.defn(name="emit_reproducible_artifact_v1")
    async def bad_artifact_activity(value: ReproducibleResearchWorkflowInput) -> str:
        del value
        return "sha256:" + "f" * 64

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as environment:
        async with Worker(
            environment.client,
            task_queue="m1-incoherent-artifact-test",
            workflows=[ReproducibleResearchCaseWorkflow],
            activities=[manifest_activity, bad_artifact_activity],
        ):
            with pytest.raises(WorkflowFailureError):
                await environment.client.execute_workflow(
                    ReproducibleResearchCaseWorkflow.run,
                    command,
                    id=research_case_workflow_id(command.tenant_id, command.case_id),
                    task_queue="m1-incoherent-artifact-test",
                )
