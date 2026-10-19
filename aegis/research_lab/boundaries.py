"""Locked-component and candidate-overlay path boundaries."""

from __future__ import annotations

from pathlib import Path

from aegis.contracts import canonical_sha256


class CandidateBoundaryError(ValueError):
    pass


_ALLOWED_PREFIXES = (
    "skills/candidates/",
    "aegis/agents/candidates/",
    "configs/models/candidates/",
    "configs/sources/candidates/",
    "aegis/quant/features/candidates/",
    "configs/strategies/candidates/",
    "data/memory/candidates/",
)
_LOCKED_PREFIXES = (
    "aegis/data/",
    "aegis/fund/run_cycle.py",
    "aegis/brokers/",
    "aegis/risk/",
    "aegis/fund/ledger.py",
    "aegis/research_lab/",
)


def validate_candidate_target(root: str | Path, target: str | Path) -> Path:
    project_root = Path(root).resolve()
    raw = Path(target)
    if raw.is_absolute() or ".." in raw.parts:
        raise CandidateBoundaryError("candidate target escapes the project")
    candidate = (project_root / raw).resolve()
    if not candidate.is_relative_to(project_root):
        raise CandidateBoundaryError("candidate target escapes the project")
    relative = candidate.relative_to(project_root).as_posix()
    if any(relative == locked or relative.startswith(locked) for locked in _LOCKED_PREFIXES):
        raise CandidateBoundaryError("candidate target is a locked component")
    if not any(relative.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
        raise CandidateBoundaryError("candidate target is outside candidate-only surfaces")
    parent = candidate.parent
    while parent != project_root:
        if parent.is_symlink():
            raise CandidateBoundaryError("candidate target crosses a symlink")
        parent = parent.parent
    return candidate


def validate_patch_scope(patch_text: str, target_path: str) -> None:
    """Require a text unified diff whose every file header matches the declared target."""
    if "\x00" in patch_text or "GIT binary patch" in patch_text:
        raise CandidateBoundaryError("candidate patch must be a text-only unified diff")
    expected = Path(target_path).as_posix()
    headers: list[tuple[str, str]] = []
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) != 4 or not parts[2].startswith("a/") or not parts[3].startswith("b/"):
                raise CandidateBoundaryError("candidate patch has a malformed diff header")
            headers.append((parts[2][2:], parts[3][2:]))
        elif line.startswith("--- ") or line.startswith("+++ "):
            path = line[4:].split("\t", 1)[0]
            if path != "/dev/null" and path.removeprefix("a/").removeprefix("b/") != expected:
                raise CandidateBoundaryError("candidate patch touches an undeclared path")
    if not headers or any(old != expected or new != expected for old, new in headers):
        raise CandidateBoundaryError("candidate patch is not confined to its declared target")


def candidate_overlay_hash(base_tree_hash: str, patch_hash: str, target_path: str) -> str:
    return canonical_sha256(
        {
            "base_tree_hash": base_tree_hash,
            "patch_hash": patch_hash,
            "target_path": Path(target_path).as_posix(),
        }
    )
