"""Runtime capability authorization; Markdown metadata is not the security boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from aegis.contracts import RunMode
from aegis.harness.budgets import Budget, BudgetState
from aegis.harness.skill_loader import SkillDefinition

_FORBIDDEN_AGENT_PREFIXES = ("broker.", "execution.", "risk.", "promotion.")
_LIVE_ONLY_PREFIXES = (
    "source.agent_reach.",
    "source.scrapling.",
    "source.browser.",
    "source.direct_http.",
)


class CapabilityDenied(PermissionError):
    pass


class CapabilityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    role: str
    skill: str
    tool: str
    mode: RunMode
    reason: str


class CapabilityBroker:
    def __init__(self, mode: RunMode) -> None:
        self.mode = mode
        self._budgets: dict[tuple[str, str], BudgetState] = {}

    def register(self, role: str, skill: SkillDefinition) -> None:
        if role not in skill.metadata.roles:
            raise CapabilityDenied(f"role {role} is not permitted to use {skill.metadata.name}")
        self._budgets[(role, skill.metadata.name)] = BudgetState(
            Budget(
                max_tool_calls=skill.metadata.max_tool_calls,
                max_cost_usd=skill.metadata.max_cost_usd,
            )
        )

    def decide(self, role: str, skill: SkillDefinition, tool: str) -> CapabilityDecision:
        reason = "allowed by typed skill capability"
        allowed = True
        if (role, skill.metadata.name) not in self._budgets:
            allowed = False
            reason = "role/skill pair is not registered"
        elif tool not in skill.metadata.allowed_tools:
            allowed = False
            reason = "tool is not declared by the skill"
        elif tool.startswith(_FORBIDDEN_AGENT_PREFIXES):
            allowed = False
            reason = "agents cannot access capital-critical capabilities"
        elif self.mode in {"replay", "historical"} and tool.startswith(_LIVE_ONLY_PREFIXES):
            allowed = False
            reason = "live source capability is disabled by mode"
        elif self.mode == "historical" and not skill.metadata.historical_safe:
            allowed = False
            reason = "skill is not historical-safe"
        return CapabilityDecision(
            allowed=allowed,
            role=role,
            skill=skill.metadata.name,
            tool=tool,
            mode=self.mode,
            reason=reason,
        )

    def authorize(
        self, role: str, skill: SkillDefinition, tool: str, *, cost_usd: float = 0.0
    ) -> None:
        decision = self.decide(role, skill, tool)
        if not decision.allowed:
            raise CapabilityDenied(decision.reason)
        self._budgets[(role, skill.metadata.name)].charge_tool(cost_usd)
