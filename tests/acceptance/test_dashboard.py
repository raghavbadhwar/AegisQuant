from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from apps.cli import app
from tests.acceptance.test_cli_demo import _science_report_path
from tests.research_lab.test_adaptive_report import _sealed_report

ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_is_read_only_complete_audit_observer(tmp_path: Path, monkeypatch) -> None:
    ledger = tmp_path / "dashboard.sqlite"
    result = CliRunner().invoke(
        app,
        [
            "replay",
            str(ROOT / "data/fixtures/cases/nvda_earnings_case.json"),
            "--ledger",
            str(ledger),
        ],
    )
    assert result.exit_code == 0, result.output
    with sqlite3.connect(ledger) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = hashlib.sha256(ledger.read_bytes()).hexdigest()
    monkeypatch.setenv("AEGIS_LEDGER_PATH", str(ledger))
    dashboard = AppTest.from_file(str(ROOT / "apps/dashboard.py")).run(timeout=20)
    after = hashlib.sha256(ledger.read_bytes()).hexdigest()
    assert not dashboard.exception
    assert before == after
    assert [item.value for item in dashboard.title] == [
        "AegisQuant Research & Paper Portfolio Console"
    ]
    assert "read-only dashboard" in dashboard.warning[0].value
    assert [tab.label for tab in dashboard.tabs] == [
        "Case Intake",
        "Agent Graph",
        "Evidence Dossier",
        "Forecast",
        "Portfolio & Risk",
        "Audit",
        "Source Monitor",
        "Memory",
        "Research Lab",
        "Learning",
    ]
    assert len(dashboard.button) == 0
    assert len(dashboard.text_input) == 0


def test_dashboard_science_report_is_read_only_and_fails_safe(tmp_path: Path, monkeypatch) -> None:
    ledger = tmp_path / "dashboard-science.sqlite"
    result = CliRunner().invoke(
        app,
        [
            "replay",
            str(ROOT / "data/fixtures/cases/nvda_earnings_case.json"),
            "--ledger",
            str(ledger),
        ],
    )
    assert result.exit_code == 0, result.output
    report_path = _science_report_path(tmp_path)
    before = hashlib.sha256(report_path.read_bytes()).hexdigest()
    science_ledger = tmp_path / "science.sqlite"
    ledger_before = hashlib.sha256(science_ledger.read_bytes()).hexdigest()
    monkeypatch.setenv("AEGIS_LEDGER_PATH", str(ledger))
    monkeypatch.setenv("AEGIS_SCIENCE_REPORT_PATH", str(report_path))
    monkeypatch.setenv("AEGIS_SCIENCE_LEDGER_PATH", str(science_ledger))

    dashboard = AppTest.from_file(str(ROOT / "apps/dashboard.py")).run(timeout=20)
    assert not dashboard.exception
    assert hashlib.sha256(report_path.read_bytes()).hexdigest() == before
    assert hashlib.sha256(science_ledger.read_bytes()).hexdigest() == ledger_before
    assert any(item.value == "Candidate-only v6 Science Report" for item in dashboard.subheader)
    assert any(
        json.loads(item.value).get("verification", {}).get("claim_strength") == "limited"
        for item in dashboard.json
    )
    assert len(dashboard.button) == 0
    assert len(dashboard.text_input) == 0

    missing_ledger = tmp_path / "missing-science.sqlite"
    monkeypatch.setenv("AEGIS_SCIENCE_LEDGER_PATH", str(missing_ledger))
    missing = AppTest.from_file(str(ROOT / "apps/dashboard.py")).run(timeout=20)
    assert not missing.exception
    assert any("Science report unavailable" in item.value for item in missing.error)
    assert not missing_ledger.exists()

    monkeypatch.setenv("AEGIS_SCIENCE_LEDGER_PATH", str(science_ledger))
    report_path.write_text("not valid JSON")
    invalid = AppTest.from_file(str(ROOT / "apps/dashboard.py")).run(timeout=20)
    assert not invalid.exception
    assert any("Science report unavailable" in item.value for item in invalid.error)


def test_dashboard_adaptive_report_is_independent_and_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    _, report_path, index_path = _sealed_report(tmp_path)
    report_before = hashlib.sha256(report_path.read_bytes()).hexdigest()
    index_before = hashlib.sha256(index_path.read_bytes()).hexdigest()
    missing_cycle_ledger = tmp_path / "missing-cycle.sqlite"
    monkeypatch.setenv("AEGIS_LEDGER_PATH", str(missing_cycle_ledger))
    monkeypatch.setenv("AEGIS_ADAPTIVE_REPORT_PATH", str(report_path))
    monkeypatch.setenv("AEGIS_ADAPTIVE_EVIDENCE_INDEX_PATH", str(index_path))

    dashboard = AppTest.from_file(str(ROOT / "apps/dashboard.py")).run(timeout=20)

    assert not dashboard.exception
    assert any(item.value == "Adaptive Research (read-only)" for item in dashboard.subheader)
    assert any(
        json.loads(item.value).get("status", {}).get("authority") == "candidate_only"
        for item in dashboard.json
    )
    assert hashlib.sha256(report_path.read_bytes()).hexdigest() == report_before
    assert hashlib.sha256(index_path.read_bytes()).hexdigest() == index_before
    assert not missing_cycle_ledger.exists()


def test_dashboard_rejects_invalid_adaptive_report_without_writes(
    tmp_path: Path, monkeypatch
) -> None:
    _, report_path, index_path = _sealed_report(tmp_path)
    report_path.write_text("not valid JSON")
    report_before = hashlib.sha256(report_path.read_bytes()).hexdigest()
    index_before = hashlib.sha256(index_path.read_bytes()).hexdigest()
    missing_cycle_ledger = tmp_path / "missing-cycle.sqlite"
    monkeypatch.setenv("AEGIS_LEDGER_PATH", str(missing_cycle_ledger))
    monkeypatch.setenv("AEGIS_ADAPTIVE_REPORT_PATH", str(report_path))
    monkeypatch.setenv("AEGIS_ADAPTIVE_EVIDENCE_INDEX_PATH", str(index_path))

    dashboard = AppTest.from_file(str(ROOT / "apps/dashboard.py")).run(timeout=20)

    assert not dashboard.exception
    assert any("Adaptive report rejected" in item.value for item in dashboard.error)
    assert hashlib.sha256(report_path.read_bytes()).hexdigest() == report_before
    assert hashlib.sha256(index_path.read_bytes()).hexdigest() == index_before
    assert not missing_cycle_ledger.exists()
