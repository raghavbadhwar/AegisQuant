from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAN_COMMAND = "git status --porcelain=v1 --untracked-files=all"


def test_documented_and_ci_release_gates_require_clean_worktree() -> None:
    checklist = (ROOT / "docs/RELEASE_CHECKLIST.md").read_text()
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert CLEAN_COMMAND in checklist
    assert CLEAN_COMMAND in workflow
