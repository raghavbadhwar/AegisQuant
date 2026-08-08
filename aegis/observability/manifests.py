"""Case reproducibility manifests and local build fingerprints."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ReproducibilityManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code_revision: str
    code_tree_hash: str
    environment_lock_hash: str
    data_snapshot_hash: str
    dataset_hash: str
    source_manifest_versions: dict[str, str] = Field(default_factory=dict)
    raw_evidence_hashes: dict[str, str] = Field(default_factory=dict)
    memory_snapshot_hash: str
    relation_snapshot_hash: str
    skill_versions: list[str] = Field(default_factory=list)
    prompt_versions: list[str] = Field(default_factory=list)
    model_deployments: list[str] = Field(default_factory=list)
    embedding_versions: list[str] = Field(default_factory=list)
    reranker_versions: list[str] = Field(default_factory=list)
    cost_assumptions: dict[str, float] = Field(default_factory=dict)
    random_seeds: dict[str, int] = Field(default_factory=dict)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_revision(root: Path) -> str:
    head_path = root / ".git/HEAD"
    if not head_path.is_file():
        return "unknown"
    head = head_path.read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head
    ref_path = root / ".git" / head.removeprefix("ref: ")
    return ref_path.read_text(encoding="utf-8").strip() if ref_path.is_file() else "unknown"


@lru_cache(maxsize=4)
def local_build_fingerprint(root: Path) -> tuple[str, str, str]:
    """Hash deterministic source/config inputs without shelling out."""
    digest = hashlib.sha256()
    roots = [root / "aegis", root / "apps", root / "configs", root / "policies"]
    files: list[Path] = [root / "pyproject.toml", root / "uv.lock"]
    for directory in roots:
        if directory.exists():
            files.extend(path for path in directory.rglob("*") if path.is_file())
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    lock = root / "uv.lock"
    return _git_revision(root), digest.hexdigest(), _sha256_file(lock)
