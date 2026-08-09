from pathlib import Path

from aegis.pit_data.builder import bootstrap


def test_bootstrap_creates_only_empty_local_lake_structure(tmp_path: Path) -> None:
    root = bootstrap(tmp_path / "pit")
    assert (root / "raw" / "sec").is_dir()
    assert (root / "normalized").is_dir()
    assert (root / "snapshots").is_dir()
    assert "Synthetic data is prohibited" in (root / "README.md").read_text()
