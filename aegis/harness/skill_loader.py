"""Strict loader for versioned Markdown reasoning protocols."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256

_REQUIRED_SECTIONS = (
    "Objective",
    "Non-goals",
    "Preconditions",
    "Inputs",
    "Allowed tools",
    "Procedure",
    "Deterministic calculations",
    "Evidence contract",
    "Abstention and halt conditions",
    "Output contract",
    "Verification checklist",
    "Failure modes",
    "Memory policy",
    "Evaluation cases",
    "Version history",
)
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class SkillValidationError(ValueError):
    pass


class SkillMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    version: str
    owner: str = Field(min_length=1)
    roles: tuple[str, ...] = Field(min_length=1)
    inputs: tuple[str, ...] = Field(min_length=1)
    outputs: tuple[str, ...] = Field(min_length=1)
    allowed_tools: tuple[str, ...]
    historical_safe: bool
    memory_read: tuple[str, ...]
    memory_write: str
    model_alias: str = Field(min_length=1)
    max_tool_calls: int = Field(ge=0)
    max_cost_usd: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def semantic_version_and_candidate_memory(self) -> SkillMetadata:
        if not _VERSION.fullmatch(self.version):
            raise ValueError("skill version must use semantic x.y.z form")
        if self.memory_write not in {"none", "candidate-only", "working-only"}:
            raise ValueError("skill memory_write must be bounded")
        return self


class SkillDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: SkillMetadata
    body: str
    path: str
    content_hash: str

    @property
    def version_id(self) -> str:
        return f"{self.metadata.name}@{self.metadata.version}"


def load_skill(path: str | Path, *, root: str | Path | None = None) -> SkillDefinition:
    candidate = Path(path).resolve()
    if root is not None:
        allowed_root = Path(root).resolve()
        if not candidate.is_relative_to(allowed_root):
            raise SkillValidationError("skill path escapes the allowed root")
    text = candidate.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillValidationError("skill must start with YAML frontmatter")
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise SkillValidationError("skill frontmatter is not closed") from exc
    try:
        raw_metadata = yaml.safe_load("\n".join(lines[1:closing]))
        metadata = SkillMetadata.model_validate(raw_metadata)
    except Exception as exc:
        raise SkillValidationError(f"invalid skill metadata: {candidate}") from exc
    body = "\n".join(lines[closing + 1 :]).strip()
    headings = re.findall(r"^##\s+(.+?)\s*$", body, flags=re.MULTILINE)
    missing = [heading for heading in _REQUIRED_SECTIONS if heading not in headings]
    if missing:
        raise SkillValidationError(f"skill is missing required sections: {missing}")
    python_blocks = re.findall(r"```python\n(.*?)```", body, flags=re.DOTALL)
    if any(len(block.splitlines()) > 40 for block in python_blocks):
        raise SkillValidationError("skills may not embed large Python implementations")
    return SkillDefinition(
        metadata=metadata,
        body=body,
        path=candidate.as_posix(),
        content_hash=canonical_sha256({"metadata": metadata, "body": body}),
    )


def load_skill_tree(root: str | Path) -> dict[str, SkillDefinition]:
    skill_root = Path(root).resolve()
    definitions: dict[str, SkillDefinition] = {}
    for path in sorted(skill_root.rglob("SKILL.md")):
        definition = load_skill(path, root=skill_root)
        name = definition.metadata.name
        if name in definitions:
            raise SkillValidationError(f"duplicate skill name: {name}")
        definitions[name] = definition
    return definitions
