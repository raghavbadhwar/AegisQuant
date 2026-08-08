"""Loader for versioned Markdown agent prompts and provenance identities."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from aegis.contracts import canonical_sha256

_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class AgentPromptError(ValueError):
    pass


class AgentPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    version: str
    role: str = Field(min_length=1)
    model_alias: str = Field(min_length=1)
    skills: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    historical_safe: bool
    memory_read: tuple[str, ...]
    memory_write: str
    max_tool_calls: int = Field(ge=0)
    max_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    body: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def version_id(self) -> str:
        return f"{self.name}@{self.version}#{self.content_hash[:12]}"


def load_agent_prompt(path: str | Path, *, root: str | Path) -> AgentPrompt:
    candidate = Path(path).resolve()
    allowed_root = Path(root).resolve()
    if not candidate.is_relative_to(allowed_root):
        raise AgentPromptError("agent path escapes the allowed root")
    lines = candidate.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise AgentPromptError("agent prompt must start with YAML frontmatter")
    try:
        closing = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
        metadata = yaml.safe_load("\n".join(lines[1:closing]))
    except Exception as exc:
        raise AgentPromptError("invalid agent prompt frontmatter") from exc
    if not isinstance(metadata, dict) or not _VERSION.fullmatch(str(metadata.get("version", ""))):
        raise AgentPromptError("agent prompt requires semantic version")
    body = "\n".join(lines[closing + 1 :]).strip()
    payload = {**metadata, "body": body}
    try:
        return AgentPrompt.model_validate({**payload, "content_hash": canonical_sha256(payload)})
    except Exception as exc:
        raise AgentPromptError("invalid agent prompt contract") from exc


def load_agent_tree(root: str | Path) -> dict[str, AgentPrompt]:
    prompt_root = Path(root).resolve()
    prompts: dict[str, AgentPrompt] = {}
    for path in sorted(prompt_root.rglob("AGENT.md")):
        prompt = load_agent_prompt(path, root=prompt_root)
        if prompt.name in prompts:
            raise AgentPromptError(f"duplicate agent name: {prompt.name}")
        prompts[prompt.name] = prompt
    return prompts
