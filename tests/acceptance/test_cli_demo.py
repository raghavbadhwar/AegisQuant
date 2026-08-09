from __future__ import annotations

import json
import socket
from pathlib import Path

from typer.testing import CliRunner

from apps.cli import app

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

    strategy_outputs = []
    fund_outputs = []
    for index in range(2):
        strategy = runner.invoke(
            app,
            [
                "strategy",
                "evaluate",
                "--fixture",
                str(ROOT / "data/fixtures/v3b/strategy_returns.json"),
                "--ledger",
                str(tmp_path / f"experiment-{index}.sqlite"),
            ],
        )
        assert strategy.exit_code == 0, strategy.output
        strategy_outputs.append(strategy.stdout)
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

    assert strategy_outputs[0].encode() == strategy_outputs[1].encode()
    comparison = json.loads(strategy_outputs[0])
    assert [row["strategy_id"] for row in comparison["baselines"]] == [
        "equal-weight-v1",
        "inverse-vol-v1",
        "simple-factor-v1",
        "fundamental-only-v1",
        "quant-only-v1",
        "combined-multistrategy-v1",
    ]
    assert comparison["combined_status"] == "eligible"
    assert fund_outputs[0].encode() == fund_outputs[1].encode()
    record = json.loads(fund_outputs[0])
    assert record["schema_version"] == "aegis-cycle-v2"
    assert record["master_portfolio"]["contributions"]
    assert record["portfolio"]["target_weights"] == record["master_portfolio"]["target_weights"]
    help_result = runner.invoke(app, ["fund", "--help"])
    assert help_result.exit_code == 0
    assert "backtest" in help_result.stdout
