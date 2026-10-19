"""Deterministic per-case capability budgets."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BudgetExceeded(RuntimeError):
    pass


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_tool_calls: int = Field(ge=0)
    max_cost_usd: float = Field(ge=0, allow_inf_nan=False)
    max_tokens: int = Field(default=20_000, gt=0)
    max_retries: int = Field(default=1, ge=0)


class BudgetState:
    def __init__(self, budget: Budget) -> None:
        self.budget = budget
        self.tool_calls = 0
        self.cost_usd = 0.0
        self.tokens = 0
        self.retries = 0

    def charge_tool(self, cost_usd: float = 0.0) -> None:
        if cost_usd < 0:
            raise ValueError("cost cannot be negative")
        if self.tool_calls + 1 > self.budget.max_tool_calls:
            raise BudgetExceeded("tool-call budget exhausted")
        if self.cost_usd + cost_usd > self.budget.max_cost_usd + 1e-12:
            raise BudgetExceeded("cost budget exhausted")
        self.tool_calls += 1
        self.cost_usd += cost_usd

    def charge_tokens(self, count: int) -> None:
        if count < 0:
            raise ValueError("token count cannot be negative")
        if self.tokens + count > self.budget.max_tokens:
            raise BudgetExceeded("token budget exhausted")
        self.tokens += count

    def charge_retry(self) -> None:
        if self.retries + 1 > self.budget.max_retries:
            raise BudgetExceeded("retry budget exhausted")
        self.retries += 1
