"""Hash-bound Pydantic builder for persisted fundamental artifacts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from aegis.contracts import canonical_sha256


def build_hashed[ModelT: BaseModel](model: type[ModelT], **values: Any) -> ModelT:
    draft = model.model_construct(**values, content_hash="0" * 64)
    payload = draft.model_dump(exclude={"content_hash"})
    return model(**values, content_hash=canonical_sha256(payload))
