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
