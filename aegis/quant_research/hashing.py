"""Canonical constructor for hash-bound v3B contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from aegis.contracts import canonical_sha256


def build_hashed[T: BaseModel](contract: type[T], /, **payload: Any) -> T:
    """Validate a contract after binding its defaults and payload to SHA-256."""
    draft = contract.model_construct(**payload)
    hashed_payload = draft.model_dump(exclude={"content_hash"})
    return contract(**payload, content_hash=canonical_sha256(hashed_payload))
