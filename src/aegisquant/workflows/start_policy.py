"""Tenant-bound Temporal workflow identity and duplicate-start policy."""

from uuid import UUID

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

RESEARCH_CASE_ID_REUSE_POLICY = WorkflowIDReusePolicy.REJECT_DUPLICATE
RESEARCH_CASE_ID_CONFLICT_POLICY = WorkflowIDConflictPolicy.FAIL


def research_case_workflow_id(tenant_id: str, case_id: UUID) -> str:
    normalized = tenant_id.strip()
    if not normalized:
        raise ValueError("tenant_id must not be empty")
    return f"research-case-v1:{normalized}:{case_id}"
