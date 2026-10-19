import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar
from uuid import UUID

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from aegisquant.contracts.artifact import BlobRef
from aegisquant.security.digests import digest_canonical
from aegisquant.workflows.contracts import ResearchCaseWorkflowInput, SnapshotRef
from aegisquant.workflows.fixture_activities import FIXTURE_ACTIVITIES
from aegisquant.workflows.research_case import ResearchCaseWorkflow

D = "sha256:" + "a" * 64
T = TypeVar("T")


class FaultPoint(StrEnum):
    BEFORE_COMMIT = "before_commit"
    AFTER_COMMIT_BEFORE_ACK = "after_commit_before_ack"


class IdempotencyConflictProbe(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredEffect[T]:
    request_digest: str
    result: T


class TestEffectStore:
    """Test oracle for the Activity commit/ack boundary; not production storage."""

    __test__ = False

    def __init__(self, fault: FaultPoint | None = None) -> None:
        self.fault = fault
        self.attempts: list[int] = []
        self.records: dict[tuple[str, str], StoredEffect[object]] = {}
        self._lock = asyncio.Lock()

    async def execute(
        self,
        *,
        key: tuple[str, str],
        attempt: int,
        request_digest: str,
        effect: Callable[[], T],
    ) -> T:
        async with self._lock:
            self.attempts.append(attempt)
            existing = self.records.get(key)
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise IdempotencyConflictProbe("operation key reused with changed input")
                return existing.result  # type: ignore[return-value]
            if self.fault is FaultPoint.BEFORE_COMMIT and attempt == 1:
                raise RuntimeError("injected crash before commit")
            result = effect()
            self.records[key] = StoredEffect(
                request_digest=request_digest,
                result=result,
            )
            if self.fault is FaultPoint.AFTER_COMMIT_BEFORE_ACK and attempt == 1:
                raise RuntimeError("injected crash after commit before activity ack")
            return result


def command() -> ResearchCaseWorkflowInput:
    return ResearchCaseWorkflowInput(
        tenant_id="tenant-a",
        case_id=UUID("00000000-0000-0000-0000-000000000201"),
        data_snapshot_id="fixture-snapshot-v1",
        fixture_evidence=BlobRef(
            tenant_id="tenant-a",
            uri="fixture://approved/idempotency-v1",
            content_digest=D,
            size_bytes=1,
            media_type="text/plain",
            retention_class="test",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", list(FaultPoint))
async def test_activity_retry_commits_one_logical_effect(fault: FaultPoint) -> None:
    store = TestEffectStore(fault)

    @activity.defn(name="freeze_fixture_snapshot_v1")
    async def faulted_snapshot(value: ResearchCaseWorkflowInput) -> SnapshotRef:
        info = activity.info()
        return await store.execute(
            key=(info.workflow_id, info.activity_id),
            attempt=info.attempt,
            request_digest=digest_canonical(value),
            effect=lambda: SnapshotRef(
                tenant_id=value.tenant_id,
                snapshot_id=value.data_snapshot_id,
                manifest_digest=D,
            ),
        )

    value = command()
    task_queue = f"m0-idempotency-{fault.value}"
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ResearchCaseWorkflow],
            activities=[faulted_snapshot, *FIXTURE_ACTIVITIES[1:]],
        ):
            result = await environment.client.execute_workflow(
                ResearchCaseWorkflow.run,
                value,
                id=f"{task_queue}-workflow",
                task_queue=task_queue,
            )

    assert store.attempts == [1, 2]
    assert len(store.records) == 1
    stored = next(iter(store.records.values()))
    assert result.snapshot == stored.result


@pytest.mark.asyncio
async def test_activity_operation_key_fails_closed_on_changed_input() -> None:
    store = TestEffectStore()
    key = ("workflow", "activity")
    result = SnapshotRef(
        tenant_id="tenant-a",
        snapshot_id="snapshot",
        manifest_digest=D,
    )
    await store.execute(
        key=key,
        attempt=1,
        request_digest="sha256:" + "b" * 64,
        effect=lambda: result,
    )
    with pytest.raises(IdempotencyConflictProbe, match="changed input"):
        await store.execute(
            key=key,
            attempt=2,
            request_digest="sha256:" + "c" * 64,
            effect=lambda: result,
        )
    assert len(store.records) == 1
