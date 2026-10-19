"""Logical model aliases and a fail-closed deterministic replay provider."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from aegis.contracts import canonical_sha256


class ModelProviderError(RuntimeError):
    pass


class ModelInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    model_alias: str
    actual_model: str
    input_hash: str
    fixture_hash: str
    output: dict[str, Any]
    tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)


class ModelProvider(Protocol):
    network_enabled: bool

    def invoke(self, role: str, model_alias: str, input_hash: str) -> ModelInvocation: ...


class ReplayModelProvider:
    network_enabled = False

    def __init__(self, fixture_path: str | Path, expected_case_id: str) -> None:
        self.path = Path(fixture_path).resolve()
        if not self.path.is_file():
            raise ModelProviderError(f"missing replay model fixture: {self.path}")
        raw = self.path.read_bytes()
        try:
            payload = json.loads(raw)
        except Exception as exc:
            raise ModelProviderError("invalid replay model fixture JSON") from exc
        self.fixture_hash = canonical_sha256(payload)
        if payload.get("case_id") != expected_case_id:
            raise ModelProviderError("replay model fixture case mismatch")
        version = payload.get("version")
        roles = payload.get("roles")
        if not isinstance(version, str) or not isinstance(roles, dict):
            raise ModelProviderError("replay model fixture schema is invalid")
        self.version = version
        self.roles: dict[str, dict[str, Any]] = {}
        for role, output in roles.items():
            if not isinstance(role, str) or not isinstance(output, dict):
                raise ModelProviderError("replay role output must be a JSON object")
            self.roles[role] = output

    def invoke(self, role: str, model_alias: str, input_hash: str) -> ModelInvocation:
        if role not in self.roles:
            raise ModelProviderError(f"missing replay output for role: {role}")
        return ModelInvocation(
            role=role,
            model_alias=model_alias,
            actual_model=f"replay/{self.version}/{role}",
            input_hash=input_hash,
            fixture_hash=self.fixture_hash,
            output=copy.deepcopy(self.roles[role]),
            tokens=0,
            cost_usd=0.0,
        )
