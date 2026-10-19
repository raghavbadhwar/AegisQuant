"""Offline case operator commands with no HTTP execution surface."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, NoReturn

from pydantic import field_validator

from aegisquant.case_ledger.postgres import digest_jsonb
from aegisquant.contracts.common import FixedDecimal, Identifier, Sha256Digest, StrictModel
from aegisquant.contracts.learning import (
    LearningCandidate,
    LearningEvaluationV2,
    LearningProposalManifest,
    PromotionApprovalV2,
)
from aegisquant.contracts.recovery import ObjectStoreRecoveryCommand, ObjectStoreRecoveryReceipt
from aegisquant.contracts.release import ReleaseVerificationInput
from aegisquant.contracts.venue import VenueConformanceInput
from aegisquant.control_api import dependency_readiness
from aegisquant.fixture_case import FixtureCaseReport, FixtureCaseSpec, run_fixture_case
from aegisquant.learning.governance import approve_candidate_v2, evaluate_candidate_v2
from aegisquant.learning.loop import propose_candidate, verify_learning_records
from aegisquant.object_store import LocalImmutableObjectStore
from aegisquant.object_store.recovery import run_local_object_store_recovery_drill
from aegisquant.quant.multi_period import MultiPeriodCaseReport, MultiPeriodCaseSpec
from aegisquant.security.digests import digest_canonical
from aegisquant.security.release_attestation import (
    ProductionReleaseVerifier,
    load_release_trust_store,
)
from aegisquant.security.risk_signing import load_risk_trust_store, trusted_risk_keys_from_store
from aegisquant.venue.conformance import verify_venue_conformance


class ReportVerificationError(Exception):
    pass


class _ProposeInput(StrictModel):
    source_spec: MultiPeriodCaseSpec
    source_report: MultiPeriodCaseReport
    baseline_spec: FixtureCaseSpec
    candidate_id: Identifier
    source_actor_id: Identifier
    independent_evaluator_id: Identifier
    evaluation_plan_digest: Sha256Digest
    rollback_manifest_digest: Sha256Digest
    strategy_parameter: Literal["portfolio_policy.uncertainty_floor"]
    proposed_value: FixedDecimal
    now: datetime
    candidate_matures_at: datetime

    @field_validator("now", "candidate_matures_at", mode="before")
    @classmethod
    def parse_times(cls, value: object) -> object:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )


class _EvaluateInput(StrictModel):
    candidate: LearningCandidate
    proposal: LearningProposalManifest
    evaluator_id: Identifier
    evaluation_manifest_digest: Sha256Digest
    shadow_passed: bool
    canary_passed: bool
    now: datetime

    @field_validator("now", mode="before")
    @classmethod
    def parse_time(cls, value: object) -> object:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )


class _ApproveInput(StrictModel):
    candidate: LearningCandidate
    proposal: LearningProposalManifest
    evaluation: LearningEvaluationV2
    approver_id: Identifier
    approver_is_human: bool
    rollback_manifest_digest: Sha256Digest
    now: datetime
    expires_at: datetime

    @field_validator("now", "expires_at", mode="before")
    @classmethod
    def parse_time(cls, value: object) -> object:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )


class _VerifyInput(StrictModel):
    candidate: LearningCandidate
    proposal: LearningProposalManifest
    evaluation: LearningEvaluationV2
    approval: PromotionApprovalV2
    source_spec: MultiPeriodCaseSpec
    source_report: MultiPeriodCaseReport


def _fixture(path: Path) -> FixtureCaseSpec:
    return FixtureCaseSpec.model_validate_json(path.read_bytes())


def _report(path: Path) -> FixtureCaseReport:
    return FixtureCaseReport.model_validate_json(path.read_bytes())


def _result_digest(report: FixtureCaseReport) -> str:
    return digest_jsonb(report.model_dump(mode="json"))


def _write_json(value: object) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _verified_replay(fixture_path: Path, report_path: Path) -> FixtureCaseReport:
    stored = _report(report_path)
    replayed = run_fixture_case(_fixture(fixture_path))
    if replayed != stored:
        raise ReportVerificationError("report does not match deterministic replay")
    return replayed


def _run(args: argparse.Namespace) -> int:
    report = run_fixture_case(_fixture(args.fixture))
    rendered = report.model_dump_json(indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


def _verify(args: argparse.Namespace) -> int:
    report = _verified_replay(args.fixture, args.report)
    _write_json({"verified": True, "result_digest": _result_digest(report)})
    return 0


def _replay(args: argparse.Namespace) -> int:
    report = _verified_replay(args.fixture, args.report)
    _write_json({"replayed": True, "result_digest": _result_digest(report)})
    return 0


def _inspect(args: argparse.Namespace) -> int:
    report = _report(args.report)
    _write_json(
        {
            "tenant_id": report.tenant_id,
            "case_id": str(report.case_id),
            "mode": report.mode,
            "result_digest": _result_digest(report),
            "account_state_sequence": report.final_account.state_sequence,
            "fill_count": len(report.fills),
            "declared_reconciled": report.reconciled,
            "declared_ledger_verified": report.ledger_verified,
            "verification_performed": False,
        }
    )
    return 0


def _learning_propose(args: argparse.Namespace) -> int:
    request = _ProposeInput.model_validate_json(args.input.read_bytes())
    result = propose_candidate(
        source_spec=request.source_spec,
        source_report=request.source_report,
        baseline_spec=request.baseline_spec,
        candidate_id=request.candidate_id,
        source_actor_id=request.source_actor_id,
        independent_evaluator_id=request.independent_evaluator_id,
        evaluation_plan_digest=request.evaluation_plan_digest,
        rollback_manifest_digest=request.rollback_manifest_digest,
        strategy_parameter=request.strategy_parameter,
        proposed_value=request.proposed_value,
        now=request.now,
        candidate_matures_at=request.candidate_matures_at,
    )
    sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    return 0


def _learning_evaluate(args: argparse.Namespace) -> int:
    request = _EvaluateInput.model_validate_json(args.input.read_bytes())
    evaluation = evaluate_candidate_v2(
        request.candidate,
        request.proposal,
        evaluator_id=request.evaluator_id,
        evaluation_manifest_digest=request.evaluation_manifest_digest,
        shadow_passed=request.shadow_passed,
        canary_passed=request.canary_passed,
        now=request.now,
    )
    sys.stdout.write(evaluation.model_dump_json(indent=2) + "\n")
    return 0


def _learning_approve(args: argparse.Namespace) -> int:
    request = _ApproveInput.model_validate_json(args.input.read_bytes())
    approval = approve_candidate_v2(
        request.candidate,
        request.proposal,
        request.evaluation,
        approver_id=request.approver_id,
        approver_is_human=request.approver_is_human,
        rollback_manifest_digest=request.rollback_manifest_digest,
        now=request.now,
        expires_at=request.expires_at,
    )
    sys.stdout.write(approval.model_dump_json(indent=2) + "\n")
    return 0


def _learning_verify(args: argparse.Namespace) -> int:
    request = _VerifyInput.model_validate_json(args.input.read_bytes())
    proposal = verify_learning_records(
        request.candidate,
        request.proposal,
        request.evaluation,
        request.approval,
        source_spec=request.source_spec,
        source_report=request.source_report,
    )
    _write_json(
        {
            "structurally_verified": True,
            "promotion_authorized": False,
            "proposal": proposal.model_dump(mode="json"),
        }
    )
    return 0


def _now() -> datetime:
    return datetime.now(UTC)


def _probe_release_object_store(root: Path, request: ReleaseVerificationInput) -> bool:
    if not root.is_absolute() or root.is_symlink():
        return False
    store = LocalImmutableObjectStore(root)
    metadata = root.stat()
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        return False
    data = (
        f"AEGISQUANT_RELEASE_PROBE_V1:{request.manifest.release_id}:"
        f"{digest_canonical(request.manifest)}"
    ).encode()
    reference = store.put_if_absent(
        tenant_id=request.manifest.tenant_id,
        data=data,
        media_type="application/vnd.aegisquant.release-probe",
        retention_class="release-evidence",
    )
    return store.get(reference, authenticated_tenant_id=request.manifest.tenant_id) == data


def _verify_release_evidence(root: Path, request: ReleaseVerificationInput) -> None:
    store = LocalImmutableObjectStore(root)
    for reference in request.manifest.evidence_references:
        store.get(reference.payload, authenticated_tenant_id=request.manifest.tenant_id)


def _release_verify(args: argparse.Namespace) -> int:
    request = ReleaseVerificationInput.model_validate_json(args.input.read_bytes())
    trust_store = load_release_trust_store(args.trust_store)
    if trust_store.tenant_id != request.manifest.tenant_id:
        raise ValueError("release trust store tenant does not match the manifest")
    now = _now()
    verified = ProductionReleaseVerifier(trust_store.trusted_keys).verify(
        request.manifest,
        independent_review=request.independent_review,
        operator_approval=request.operator_approval,
        now=now,
    )
    recovery_receipt = ObjectStoreRecoveryReceipt.model_validate_json(
        args.recovery_receipt.read_bytes()
    )
    if (
        recovery_receipt.tenant_id != verified.tenant_id
        or digest_canonical(recovery_receipt) != verified.backup_restore_drill_digest
        or recovery_receipt.completed_at > now
        or now - recovery_receipt.completed_at
        > timedelta(seconds=verified.max_recovery_drill_age_seconds)
    ):
        raise ValueError(
            "release recovery receipt is missing, stale, or outside the manifest scope"
        )
    dependencies = asyncio.run(dependency_readiness())
    object_store_root = os.environ.get("AEGISQUANT_OBJECT_STORE_ROOT")
    object_store_ready = bool(
        object_store_root and _probe_release_object_store(Path(object_store_root), request)
    )
    if object_store_ready and object_store_root:
        _verify_release_evidence(Path(object_store_root), request)
    runtime = dependencies | {"object_store": object_store_ready}
    if not all(runtime.values()):
        unavailable = ", ".join(sorted(name for name, ready in runtime.items() if not ready))
        raise ValueError(f"release runtime dependencies are not ready: {unavailable}")
    _write_json(
        {
            "local_prerequisites_verified": True,
            "manifest_digest": digest_canonical(verified),
            "release_id": verified.release_id,
            "broker_id": verified.broker_id,
            "broker_api_hostnames": verified.broker_api_hostnames,
            "runtime_dependencies": runtime,
            "live_execution_enabled": False,
            "next_required": "VENUE_ADAPTER_AND_EXTERNAL_ACCEPTANCE",
        }
    )
    return 0


def _recovery_drill(args: argparse.Namespace) -> int:
    command = ObjectStoreRecoveryCommand.model_validate_json(args.input.read_bytes())
    if (
        not args.source_root.is_absolute()
        or args.source_root.is_symlink()
        or not args.source_root.is_dir()
    ):
        raise ValueError("recovery source root must be an existing absolute non-symlink directory")
    if not args.target_root.is_absolute() or args.target_root.exists():
        raise ValueError("recovery target root must be a new absolute path")
    receipt = run_local_object_store_recovery_drill(
        command,
        source=LocalImmutableObjectStore(args.source_root),
        target=LocalImmutableObjectStore(args.target_root),
        completed_at=_now(),
    )
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")
    return 0


def _venue_verify(args: argparse.Namespace) -> int:
    value = VenueConformanceInput.model_validate_json(args.input.read_bytes())
    risk_trust_store = load_risk_trust_store(args.risk_trust_store)
    if risk_trust_store.tenant_id != value.release.tenant_id:
        raise ValueError("risk trust store tenant does not match the release")
    report = verify_venue_conformance(
        value.release,
        value.profile,
        value.order_bundle,
        value.command,
        risk_authorization=value.risk_authorization,
        trusted_risk_keys=trusted_risk_keys_from_store(risk_trust_store),
        lifecycles=value.lifecycles,
        now=value.now,
    )
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegisquant-case",
        description="Run and inspect deterministic offline AegisQuant PAPER cases.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a frozen fixture")
    run.add_argument("fixture", type=Path)
    run.add_argument("--output", type=Path, help="write the strict report JSON")
    run.set_defaults(handler=_run)

    for name, handler in (("verify", _verify), ("replay", _replay)):
        command = commands.add_parser(name, help=f"{name} a frozen fixture report")
        command.add_argument("fixture", type=Path)
        command.add_argument("report", type=Path)
        command.set_defaults(handler=handler)

    inspect = commands.add_parser("inspect", help="read a strict report without mutation")
    inspect.add_argument("report", type=Path)
    inspect.set_defaults(handler=_inspect)

    learning = commands.add_parser("learning", help="record a governed offline learning cycle")
    lifecycle = learning.add_subparsers(dest="learning_command", required=True)
    for name, handler in (
        ("propose", _learning_propose),
        ("evaluate", _learning_evaluate),
        ("approve", _learning_approve),
        ("verify", _learning_verify),
    ):
        command = lifecycle.add_parser(name, help=f"{name} a governed learning artifact")
        command.add_argument("input", type=Path, help="strict JSON command file")
        command.set_defaults(handler=handler)

    release = commands.add_parser("release", help="verify M6 production release prerequisites")
    release_commands = release.add_subparsers(dest="release_command", required=True)
    release_verify = release_commands.add_parser(
        "verify", help="verify signed release evidence and actual runtime dependencies"
    )
    release_verify.add_argument("input", type=Path, help="strict signed release JSON")
    release_verify.add_argument(
        "--trust-store", required=True, type=Path, help="operator-owned public-key trust policy"
    )
    release_verify.add_argument(
        "--recovery-receipt",
        required=True,
        type=Path,
        help="verified immutable-object recovery drill",
    )
    release_verify.set_defaults(handler=_release_verify)

    recovery = commands.add_parser("recovery", help="run an immutable-object recovery drill")
    recovery_commands = recovery.add_subparsers(dest="recovery_command", required=True)
    recovery_drill = recovery_commands.add_parser(
        "drill", help="restore an exact immutable-object manifest into a fresh local target"
    )
    recovery_drill.add_argument("input", type=Path, help="strict recovery drill JSON")
    recovery_drill.add_argument("--source-root", required=True, type=Path)
    recovery_drill.add_argument("--target-root", required=True, type=Path)
    recovery_drill.set_defaults(handler=_recovery_drill)

    venue = commands.add_parser("venue", help="verify a fixture-only venue conformance record")
    venue_commands = venue.add_subparsers(dest="venue_command", required=True)
    venue_verify = venue_commands.add_parser(
        "verify", help="verify exact venue fixtures with no network transport"
    )
    venue_verify.add_argument("input", type=Path, help="strict venue conformance JSON")
    venue_verify.add_argument(
        "--risk-trust-store", required=True, type=Path, help="operator-owned risk public-key policy"
    )
    venue_verify.set_defaults(handler=_venue_verify)
    return parser


def _invalid(parser: argparse.ArgumentParser, error: Exception) -> NoReturn:
    parser.exit(2, f"aegisquant-case: {' '.join(str(error).splitlines())}\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ReportVerificationError as error:
        sys.stderr.write(f"aegisquant-case: {error}\n")
        return 1
    except (OSError, ValueError) as error:
        _invalid(parser, error)


if __name__ == "__main__":
    raise SystemExit(main())
