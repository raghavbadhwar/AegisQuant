from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from apps.cli import app

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
