"""Offline case operator commands with no HTTP execution surface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from aegisquant.case_ledger.postgres import digest_jsonb
from aegisquant.fixture_case import FixtureCaseReport, FixtureCaseSpec, run_fixture_case


class ReportVerificationError(Exception):
    pass


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
