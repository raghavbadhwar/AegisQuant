from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis.fund.models import ForecastIntegrityError, load_historical_artifact_manifest


def _write_manifest(root: Path, entries: list[dict[str, str]]) -> Path:
    for name in ("forecasts.json", "evidence.jsonl", "bundle.json"):
        (root / name).write_text("{}")
    path = root / "manifest.json"
    path.write_text(
        json.dumps({"schema_version": "aegis-historical-artifacts-v1", "artifacts": entries})
    )
    return path


def test_historical_artifact_manifest_resolves_only_local_exact_triplets(tmp_path: Path) -> None:
    cutoff = "2024-02-23T21:05:00+00:00"
    manifest = _write_manifest(
        tmp_path,
        [
            {
                "as_of": cutoff,
                "forecasts": "forecasts.json",
                "evidence": "evidence.jsonl",
                "quant_bundle": "bundle.json",
            }
        ],
    )
    loaded = load_historical_artifact_manifest(manifest)
    assert tuple(loaded) == (cutoff,)
    assert all(path.parent == tmp_path for path in loaded[cutoff])


@pytest.mark.parametrize("value", ["../outside.json", "/tmp/outside.json"])
def test_historical_artifact_manifest_rejects_escaping_paths(tmp_path: Path, value: str) -> None:
    manifest = _write_manifest(
        tmp_path,
        [
            {
                "as_of": "2024-02-23T21:05:00+00:00",
                "forecasts": value,
                "evidence": "evidence.jsonl",
                "quant_bundle": "bundle.json",
            }
        ],
    )
    with pytest.raises(ForecastIntegrityError, match=r"relative|escapes"):
        load_historical_artifact_manifest(manifest)


def test_historical_artifact_manifest_rejects_duplicate_cutoffs(tmp_path: Path) -> None:
    entry = {
        "as_of": "2024-02-23T21:05:00+00:00",
        "forecasts": "forecasts.json",
        "evidence": "evidence.jsonl",
        "quant_bundle": "bundle.json",
    }
    manifest = _write_manifest(tmp_path, [entry, entry])
    with pytest.raises(ForecastIntegrityError, match="unique"):
        load_historical_artifact_manifest(manifest)
