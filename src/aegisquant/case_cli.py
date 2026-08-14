"""Offline case operator commands with no HTTP execution surface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
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
from aegisquant.fixture_case import FixtureCaseReport, FixtureCaseSpec, run_fixture_case
from aegisquant.learning.governance import approve_candidate_v2, evaluate_candidate_v2
from aegisquant.learning.loop import propose_candidate, verify_learning_records
from aegisquant.quant.multi_period import MultiPeriodCaseReport, MultiPeriodCaseSpec


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
