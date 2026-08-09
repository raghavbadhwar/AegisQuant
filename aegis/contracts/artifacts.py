"""Typed research artifacts and deterministic hashing helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ._base import ContractModel, validate_sha256


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_ready(value.model_dump(mode="python"))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible content deterministically as UTF-8 text."""
    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 digest of :func:`canonical_json`."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class ResearchArtifact(ContractModel):
    """A replayable specialist output with model and evidence provenance."""

    artifact_id: Annotated[str, Field(min_length=1)]
    case_id: Annotated[str, Field(min_length=1)]
    artifact_type: Annotated[str, Field(min_length=1)]
    producer_agent: Annotated[str, Field(min_length=1)]
    model_alias: Annotated[str, Field(min_length=1)]
    actual_model: Annotated[str, Field(min_length=1)]
    skill_versions: list[str] = Field(default_factory=list)
    prompt_versions: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    content_hash: str

    @field_validator("content_hash")
    @classmethod
    def content_hash_is_sha256(cls, value: str) -> str:
        return validate_sha256(value)

    @model_validator(mode="after")
    def hash_matches_payload(self) -> ResearchArtifact:
        if self.content_hash != canonical_sha256(self.payload):
            raise ValueError("content_hash does not match canonical artifact payload")
        return self
