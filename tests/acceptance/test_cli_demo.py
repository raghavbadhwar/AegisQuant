from __future__ import annotations

import json
import socket
from datetime import timedelta
from pathlib import Path

from typer.testing import CliRunner

from aegis.research_lab import (
    ExperimentLedger,
    ResearchArchive,
    ScienceReport,
    VerificationPackage,
    record_experiment_run,
)
from apps.cli import app
from tests.research_lab.test_science import AS_OF, _experiment_run, _reviewed_tree_and_plan

ROOT = Path(__file__).resolve().parents[2]


def test_no_key_replay_is_offline_and_byte_stable(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def denied(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("replay attempted network access")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setenv("OPENAI_API_KEY", "canary-must-not-be-read")
    runner = CliRunner()
    outputs: list[str] = []
    for index in range(2):
        result = runner.invoke(
            app,
            [
                "replay",
                str(ROOT / "data/fixtures/cases/nvda_earnings_case.json"),
                "--ledger",
                str(tmp_path / f"run-{index}.sqlite"),
            ],
        )
        assert result.exit_code == 0, result.output
        outputs.append(result.stdout)
    assert outputs[0].encode() == outputs[1].encode()
    payload = json.loads(outputs[0])
    assert payload["case"]["mode"] == "replay"
    assert payload["risk"]["decision"]["approved"] is True
    assert all(fill["execution_mode"] == "replay" for fill in payload["fills"])
    manifest = payload["reproducibility"]
    assert len(manifest["code_tree_hash"]) == 64
    assert len(manifest["environment_lock_hash"]) == 64
    assert len(manifest["dataset_hash"]) == 64
    assert manifest["raw_evidence_hashes"]
    assert any(name.endswith("/coordinator") for name in manifest["model_deployments"])
    assert any(name.endswith("/verifier") for name in manifest["model_deployments"])
    assert len(manifest["prompt_versions"]) == 10
    assert "canary-must-not-be-read" not in outputs[0]


def test_documented_backtest_command_succeeds(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "backtest",
            "--fund",
            "configs/funds/demo-fund.yaml",
            "--tickers",
            "AAPL,MSFT,NVDA,AMZN,GOOGL",
            "--start",
            "2024-01-01",
            "--end",
            "2024-03-31",
            "--ledger",
            str(tmp_path / "backtest.sqlite"),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["metrics"]["cycles"] == len(payload["records"])
    assert payload["metrics"]["total_cost"] > 0
    assert all(record["case"]["mode"] == "historical" for record in payload["records"])


def test_source_plan_is_typed_official_first_and_historical_denied(tmp_path: Path) -> None:
    runner = CliRunner()
    live = runner.invoke(
        app,
        ["sources", "plan", "configs/demo/live-source-request.json"],
    )
    assert live.exit_code == 0, live.output
    payload = json.loads(live.stdout)
    assert payload["source_ids"] == ["company-ir"]
    request = json.loads((ROOT / "configs/demo/live-source-request.json").read_text())
    request["mode"] = "historical"
    historical_path = tmp_path / "historical-source.json"
    historical_path.write_text(json.dumps(request))
    historical = runner.invoke(app, ["sources", "plan", str(historical_path)])
    assert historical.exit_code != 0
    assert "forbidden in historical" in str(historical.exception)


def test_v3b_cli_surface_is_offline_typed_and_byte_stable(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def denied(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("v3B CLI attempted network access")

    monkeypatch.setattr(socket, "socket", denied)
    runner = CliRunner()
    expected_keys = {
        ("demo", "screen"): "snapshot_id",
        ("demo", "factors"): "information_coefficient",
        ("demo", "events"): "cumulative_abnormal_returns",
        ("demo", "regimes"): "snapshot_id",
    }
    for command, key in expected_keys.items():
        result = runner.invoke(app, list(command))
        assert result.exit_code == 0, result.output
        assert key in json.loads(result.stdout)

    fund_outputs = []
    for index in range(2):
        strategy = runner.invoke(app, ["strategy", "evaluate"])
        assert strategy.exit_code != 0
        assert "receipt-derived historical" in strategy.output
        fund = runner.invoke(
            app,
            [
                "fund",
                "run",
                "--case",
                str(ROOT / "data/fixtures/cases/nvda_earnings_case.json"),
                "--mandate",
                str(ROOT / "configs/funds/aegis-institutional-demo-v3.yaml"),
                "--forecasts",
                str(ROOT / "data/fixtures/v3b/multi_strategy_forecasts.json"),
                "--evidence",
                str(ROOT / "data/fixtures/evidence/replay_evidence.jsonl"),
                "--ledger",
                str(tmp_path / f"fund-{index}.sqlite"),
            ],
        )
        assert fund.exit_code == 0, fund.output
        fund_outputs.append(fund.stdout)

    assert fund_outputs[0].encode() == fund_outputs[1].encode()
    record = json.loads(fund_outputs[0])
    assert record["schema_version"] == "aegis-cycle-v2"
    assert record["master_portfolio"]["contributions"]
    assert record["portfolio"]["target_weights"] == record["master_portfolio"]["target_weights"]
    help_result = runner.invoke(app, ["fund", "--help"])
    assert help_result.exit_code == 0
    assert "backtest" in help_result.stdout


def _science_report_path(tmp_path: Path) -> Path:
    tree, plan = _reviewed_tree_and_plan()
    run = _experiment_run(tree, plan)
    ledger = ExperimentLedger(tmp_path / "science.sqlite")
    assert record_experiment_run(ledger, run, tree) == run
    package = VerificationPackage(
        package_id="verification-cli",
        original_run=run,
        original_record=ledger.get(run.experiment_id),
        verifier_id="verifier-cli",
        approver_id="approver-cli",
        limitations=("Registered fixture evidence only.",),
        claim_strength_ceiling="limited",
        verified_at=AS_OF + timedelta(minutes=6),
    ).sealed()
    report = ScienceReport(
        report_id="report-cli",
        programme=tree.programme,
        archive=ResearchArchive(
            archive_id="archive-cli",
            programme_id=tree.programme.programme_id,
        ).sealed(),
        verification_package=package,
        declared_strength=package.claim_strength_ceiling,
        declared_limitations=package.limitations,
    ).sealed()
    report_path = tmp_path / "report.json"
    report_path.write_text(report.model_dump_json())
    return report_path


def test_science_view_is_read_only_byte_stable_and_rejects_action_flags(tmp_path: Path) -> None:
    report_path = _science_report_path(tmp_path)
    before = report_path.read_bytes()

    first = CliRunner().invoke(app, ["science", "view", str(report_path)])
    second = CliRunner().invoke(app, ["science", "view", str(report_path)])
    assert first.exit_code == 0, first.output
    assert first.stdout.encode() == second.stdout.encode()
    assert json.loads(first.stdout)["verification"]["claim_strength"] == "limited"
    assert report_path.read_bytes() == before
    for flag in ("--create", "--run", "--approve", "--promote", "--acquire"):
        denied = CliRunner().invoke(app, ["science", "view", str(report_path), flag])
        assert denied.exit_code != 0
        assert "No such option" in denied.output
