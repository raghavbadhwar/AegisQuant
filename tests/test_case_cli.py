import json
from pathlib import Path

import pytest

from aegisquant.case_cli import main
from aegisquant.case_ledger.postgres import digest_jsonb
from aegisquant.fixture_case import FixtureCaseReport

FIXTURE = Path("data/fixtures/cases/multi_asset_control.json")


def test_run_verify_replay_and_inspect_are_deterministic_and_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path = tmp_path / "report.json"

    assert main(("run", str(FIXTURE), "--output", str(report_path))) == 0
    first_stdout = capsys.readouterr().out
    first_bytes = report_path.read_bytes()
    assert json.loads(first_stdout) == json.loads(first_bytes)

    assert main(("run", str(FIXTURE), "--output", str(report_path))) == 0
    assert report_path.read_bytes() == first_bytes
    capsys.readouterr()

    assert main(("verify", str(FIXTURE), str(report_path))) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["verified"] is True

    report = FixtureCaseReport.model_validate_json(first_bytes)
    expected_digest = digest_jsonb(report.model_dump(mode="json"))
    assert main(("replay", str(FIXTURE), str(report_path))) == 0
    replayed = json.loads(capsys.readouterr().out)
    assert replayed == {"replayed": True, "result_digest": expected_digest}

    before_inspect = report_path.read_bytes()
    assert main(("inspect", str(report_path))) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["result_digest"] == expected_digest
    assert inspected["tenant_id"] == report.tenant_id
    assert inspected["declared_reconciled"] is True
    assert inspected["declared_ledger_verified"] is True
    assert inspected["verification_performed"] is False
    assert report_path.read_bytes() == before_inspect


def test_verify_detects_valid_json_tamper(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path = tmp_path / "report.json"
    assert main(("run", str(FIXTURE), "--output", str(report_path))) == 0
    capsys.readouterr()
    raw = json.loads(report_path.read_text())
    raw["final_nav"] = "1"
    report_path.write_text(json.dumps(raw))

    assert main(("verify", str(FIXTURE), str(report_path))) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "aegisquant-case: report does not match deterministic replay\n"


def test_invalid_json_exits_two_with_one_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_fixture = tmp_path / "bad.json"
    bad_fixture.write_text("{")

    with pytest.raises(SystemExit) as raised:
        main(("run", str(bad_fixture)))

    assert raised.value.code == 2
    error_lines = capsys.readouterr().err.splitlines()
    assert len(error_lines) == 1
    assert error_lines[0].startswith("aegisquant-case: ")
