from datetime import timedelta
from pathlib import Path

import pytest
from temporalio import workflow
from temporalio.client import WorkflowHistory
from temporalio.common import VersioningBehavior
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from aegisquant.workflows.contracts import ResearchCaseWorkflowInput, SnapshotRef
from aegisquant.workflows.durable_case import DurableOfflineCaseWorkflow
from aegisquant.workflows.research_case import ResearchCaseWorkflow
from aegisquant.workflows.research_case_v2 import ReproducibleResearchCaseWorkflow
from aegisquant.workflows.versioning import DEPLOYMENT_NAME, worker_deployment_config

FIXTURE = Path("tests/fixtures/temporal/research_case_workflow_v1.json")
V2_FIXTURE = Path("tests/fixtures/temporal/research_case_workflow_v2.json")
DURABLE_FIXTURE = Path("tests/fixtures/temporal/durable_offline_case_workflow_v1.json")
WORKFLOW_ID = "m0-golden-research-case-v1"
V2_WORKFLOW_ID = "m1-golden-research-case-v2"
DURABLE_WORKFLOW_ID = "m2-golden-durable-offline-case-v1"
V2_RUNNER = SandboxedWorkflowRunner(
    restrictions=SandboxRestrictions.default.with_passthrough_modules("pydantic_core")
)


@workflow.defn(name="ResearchCaseWorkflowV1", sandboxed=True)
class DeliberatelyIncompatibleResearchCaseWorkflow:
    @workflow.run
    async def run(self, command: ResearchCaseWorkflowInput) -> SnapshotRef:
        return await workflow.execute_activity(
            "deliberately_renamed_activity_v1",
            command,
            result_type=SnapshotRef,
            start_to_close_timeout=timedelta(seconds=30),
        )


@pytest.mark.asyncio
async def test_research_case_v1_golden_history_replays_offline() -> None:
    history = WorkflowHistory.from_json(WORKFLOW_ID, FIXTURE.read_text())
    assert len(history.events) == 23
    round_tripped = WorkflowHistory.from_json(WORKFLOW_ID, history.to_json())
    assert len(round_tripped.events) == len(history.events)

    result = await Replayer(
        workflows=[ResearchCaseWorkflow],
        data_converter=pydantic_data_converter,
        build_id="m0-golden-v1",
    ).replay_workflow(round_tripped)
    assert result.replay_failure is None


@pytest.mark.asyncio
async def test_research_case_v2_golden_history_replays_offline() -> None:
    assert V2_FIXTURE.exists()
    history = WorkflowHistory.from_json(V2_WORKFLOW_ID, V2_FIXTURE.read_text())
    result = await Replayer(
        workflows=[ReproducibleResearchCaseWorkflow],
        data_converter=pydantic_data_converter,
        build_id="m1-golden-v2",
        workflow_runner=V2_RUNNER,
    ).replay_workflow(history)
    assert result.replay_failure is None


@pytest.mark.asyncio
async def test_durable_offline_case_v1_golden_history_replays_offline() -> None:
    history = WorkflowHistory.from_json(DURABLE_WORKFLOW_ID, DURABLE_FIXTURE.read_text())
    assert len(history.events) == 23
    result = await Replayer(
        workflows=[DurableOfflineCaseWorkflow],
        data_converter=pydantic_data_converter,
        build_id="m2-golden-durable-v1",
        workflow_runner=V2_RUNNER,
    ).replay_workflow(history)
    assert result.replay_failure is None


@pytest.mark.asyncio
async def test_replay_gate_detects_an_incompatible_workflow_change() -> None:
    history = WorkflowHistory.from_json(WORKFLOW_ID, FIXTURE.read_text())
    result = await Replayer(
        workflows=[DeliberatelyIncompatibleResearchCaseWorkflow],
        data_converter=pydantic_data_converter,
    ).replay_workflow(history, raise_on_replay_failure=False)
    assert result.replay_failure is not None


def test_worker_deployment_is_pinned_and_build_id_is_required() -> None:
    config = worker_deployment_config("candidate-build-1")
    assert config.version.deployment_name == DEPLOYMENT_NAME
    assert config.version.build_id == "candidate-build-1"
    assert config.use_worker_versioning is True
    assert config.default_versioning_behavior is VersioningBehavior.PINNED
    with pytest.raises(ValueError, match="must not be empty"):
        worker_deployment_config("   ")
