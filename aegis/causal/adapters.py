"""Optional causal-tool boundary; imports no tool until it is invoked."""

from __future__ import annotations

from importlib import import_module
from typing import Protocol

from .contracts import IdentificationRecord, IdentificationRequest, IdentificationStatus


class CausalToolAbstention(RuntimeError):
    def __init__(self, status: IdentificationStatus, reason: str) -> None:
        if status == IdentificationStatus.IDENTIFIED:
            raise ValueError("an abstention cannot claim identified status")
        super().__init__(reason)
        self.status = status
        self.reason = reason


class CausalToolUnavailable(CausalToolAbstention):
    def __init__(self, reason: str) -> None:
        super().__init__(IdentificationStatus.TOOL_UNAVAILABLE, reason)


class CausalToolAdapter(Protocol):
    def identify(self, request: IdentificationRequest) -> IdentificationRecord: ...


class DoWhyAdapter:
    """Lazy availability guard; execution is intentionally not wired into v4."""

    def identify(self, request: IdentificationRequest) -> IdentificationRecord:
        try:
            IdentificationRequest.model_validate(request.model_dump(mode="json", warnings=False))
        except (AttributeError, ValueError) as exc:
            raise CausalToolAbstention(
                IdentificationStatus.NOT_IDENTIFIED,
                "invalid identification request at optional causal-tool boundary",
            ) from exc
        try:
            import_module("dowhy")
        except ImportError as exc:
            raise CausalToolUnavailable(
                "DoWhy is unavailable; causal identification abstained"
            ) from exc
        raise CausalToolAbstention(
            IdentificationStatus.NOT_IDENTIFIED,
            "DoWhy is available but no repository-owned deterministic runner is implemented",
        )
