"""Locked-component and candidate-overlay path boundaries."""

from __future__ import annotations

from pathlib import Path


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
