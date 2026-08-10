"""Shared validation primitives for public contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractModel(BaseModel):
    """Strict base for data crossing an AegisQuant boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)


class CandidateContractModel(BaseModel):
    """Frozen public candidate contract that validates every model-copy update."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        if update is not None:
            unknown_fields = set(update).difference(type(self).model_fields)
            if unknown_fields:
                names = ", ".join(sorted(unknown_fields))
                raise ValueError(f"candidate model_copy update contains unknown fields: {names}")
        copied = super().model_copy(update=update, deep=deep)
        return type(self).model_validate(copied.model_dump(mode="json"))


def normalize_ticker(value: Any) -> str:
    """Normalize and validate a US-equity ticker symbol."""
    if not isinstance(value, str):
        raise ValueError("ticker must be a string")
    ticker = value.strip().upper()
    if not _TICKER_RE.fullmatch(ticker):
        raise ValueError("ticker must contain 1-10 uppercase letters, digits, '.' or '-'")
    return ticker


def normalize_ticker_map(values: dict[str, float]) -> dict[str, float]:
    """Normalize ticker keys while rejecting aliases that collide."""
    normalized: dict[str, float] = {}
    for raw_ticker, value in values.items():
        ticker = normalize_ticker(raw_ticker)
        if ticker in normalized:
            raise ValueError(f"duplicate ticker after normalization: {ticker}")
        if not math.isfinite(value):
            raise ValueError(f"weight for {ticker} must be finite")
        normalized[ticker] = value
    return normalized


def validate_sha256(value: str) -> str:
    """Validate a lowercase hexadecimal SHA-256 digest."""
    digest = value.lower()
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError("hash must be a 64-character SHA-256 hex digest")
    return digest
