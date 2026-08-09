from pathlib import Path

import pytest

from aegis.pit_data.builder import bootstrap


def test_bootstrap_creates_only_empty_local_lake_structure(tmp_path: Path) -> None:
    root = bootstrap(tmp_path / "pit")
    assert (root / "raw" / "sec").is_dir()
    assert (root / "normalized").is_dir()
    assert (root / "snapshots").is_dir()
    assert "Synthetic data is prohibited" in (root / "README.md").read_text()


def test_ingestion_rejects_inverted_date_window(tmp_path: Path) -> None:
    from datetime import date

    from aegis.pit_data.builder import PITBuildError, ingest_sec

    with pytest.raises(PITBuildError, match="end"):
        ingest_sec(
            tmp_path,
            "AegisQuant test@example.com",
            ("AAPL",),
            filing_start=date(2022, 1, 1),
            filing_end=date(2021, 1, 1),
        )
