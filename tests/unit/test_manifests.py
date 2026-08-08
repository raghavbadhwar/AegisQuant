from __future__ import annotations

from pathlib import Path

from aegis.observability.manifests import local_build_fingerprint


def test_build_fingerprint_excludes_python_cache_artifacts(tmp_path: Path) -> None:
    (tmp_path / "aegis/__pycache__").mkdir(parents=True)
    (tmp_path / "aegis/source.py").write_text("VALUE = 1\n")
    (tmp_path / "aegis/__pycache__/source.pyc").write_bytes(b"first")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    first = local_build_fingerprint(tmp_path)
    (tmp_path / "aegis/__pycache__/source.pyc").write_bytes(b"second")
    second = local_build_fingerprint(tmp_path)
    assert first == second
