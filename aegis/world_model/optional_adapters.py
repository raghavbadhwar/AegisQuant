"""Optional offline adapter interfaces that fail closed by abstaining."""

from __future__ import annotations

from importlib.util import find_spec
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel


class OptionalAdapterAbstention(CandidateContractModel):
    """A sealed record that an optional calibration/sensitivity adapter did not run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: Literal["pymc", "salib"]
    status: Literal["abstained"] = "abstained"
    reason: Literal["dependency_unavailable", "candidate_adapter_not_enabled"]
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_content_addressed(self) -> OptionalAdapterAbstention:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("optional adapter abstention content hash mismatch")
        return self

    def sealed(self) -> OptionalAdapterAbstention:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = OptionalAdapterAbstention.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def probe_optional_adapter(adapter: Literal["pymc", "salib"]) -> OptionalAdapterAbstention:
    """Report an explicit no-I/O abstention instead of loading an optional runtime."""
    module = {"pymc": "pymc", "salib": "SALib"}[adapter]
    reason: Literal["dependency_unavailable", "candidate_adapter_not_enabled"] = (
        "candidate_adapter_not_enabled"
        if find_spec(module) is not None
        else "dependency_unavailable"
    )
    return OptionalAdapterAbstention(adapter=adapter, reason=reason).sealed()
