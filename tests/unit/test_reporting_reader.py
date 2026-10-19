from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aegis.fund.ledger import LedgerIntegrityError
from aegis.reporting import ReadOnlyRunLedger
from aegis.reporting.view_models import audit_view, portfolio_rows, run_summary
from apps.cli import app

ROOT = Path(__file__).resolve().parents[2]


def seeded_ledger(tmp_path: Path) -> Path:
    path = tmp_path / "cycles.sqlite"
    result = CliRunner().invoke(
        app,
        [
            "replay",
            str(ROOT / "data/fixtures/cases/nvda_earnings_case.json"),
            "--ledger",
            str(path),
        ],
    )
    assert result.exit_code == 0, result.output
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return path


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_only_reader_does_not_create_or_mutate_ledger(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        ReadOnlyRunLedger(missing)
    assert not missing.exists()
    path = seeded_ledger(tmp_path)
    before = file_hash(path)
    records = ReadOnlyRunLedger(path).list_records()
    after = file_hash(path)
    assert before == after
    assert len(records) == 1
    assert ReadOnlyRunLedger(path).get(records[0].run_id) == records[0]
    assert run_summary(records[0])["mode"] == "replay"
    assert portfolio_rows(records[0])
    assert audit_view(records[0])["claim_graph_hash"]


def test_read_only_reader_fails_closed_on_tampering(tmp_path: Path) -> None:
    path = seeded_ledger(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE cycles SET record_hash = ?", ("0" * 64,))
    with pytest.raises(LedgerIntegrityError, match="cycle hash mismatch"):
        ReadOnlyRunLedger(path).list_records()
