"""Security-sensitive primitive types and deterministic serialization."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints, field_validator

IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
NONCE_PATTERN = r"^[0-9a-f]{32,128}$"

Identifier = Annotated[str, StringConstraints(pattern=IDENTIFIER_PATTERN)]
Sha256Digest = Annotated[str, StringConstraints(pattern=DIGEST_PATTERN)]
Nonce = Annotated[str, StringConstraints(pattern=NONCE_PATTERN)]


def _parse_fixed_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("fixed-point values must not be booleans or binary floats")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
            raise ValueError(
                "decimal must be a plain base-10 value without exponent or leading zeros"
            )
        result = Decimal(value)
    else:
        raise ValueError("decimal must be provided as a string, integer, or Decimal")
    if not result.is_finite():
        raise ValueError("decimal must be finite")
    return Decimal(0) if result.is_zero() else result


FixedDecimal = Annotated[Decimal, BeforeValidator(_parse_fixed_decimal)]


def require_utc(value: datetime) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise ValueError("datetime must be timezone-aware")
    if offset.total_seconds() != 0:
        raise ValueError("datetime must be normalized to UTC")
    return value.astimezone(UTC)


class StrictModel(BaseModel):
    """Default contract posture: immutable, strict shape, no hidden fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    @field_validator("*", mode="before")
    @classmethod
    def normalize_unicode(cls, value: Any) -> Any:
        if isinstance(value, str):
            return unicodedata.normalize("NFC", value)
        return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("non-finite decimal is not canonical")
    if value.is_zero():
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _canonical_value(value: Any) -> Any:
    """Map accepted Python values to an injective, typed JSON representation."""

    if isinstance(value, BaseModel):
        model_name = f"{type(value).__module__}.{type(value).__qualname__}"
        return ["model", model_name, _canonical_value(value.model_dump(mode="python"))]
    if isinstance(value, Enum):
        enum_name = f"{type(value).__module__}.{type(value).__qualname__}"
        return ["enum", enum_name, _canonical_value(value.value)]
    if isinstance(value, UUID):
        return ["uuid", str(value)]
    if isinstance(value, datetime):
        value = require_utc(value)
        text = value.isoformat(timespec="microseconds").replace("+00:00", "Z")
        return ["datetime", text]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, Decimal):
        return ["decimal", _decimal_text(value)]
    if isinstance(value, str):
        return ["string", unicodedata.normalize("NFC", value)]
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["boolean", value]
    if isinstance(value, int):
        return ["integer", str(value)]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float is not canonical")
        raise TypeError("binary floats are prohibited in signed canonical payloads")
    if isinstance(value, list):
        return ["list", [_canonical_value(item) for item in value]]
    if isinstance(value, tuple):
        return ["tuple", [_canonical_value(item) for item in value]]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError("duplicate key after Unicode normalization")
            normalized[normalized_key] = _canonical_value(item)
        return ["object", [[key, normalized[key]] for key in sorted(normalized)]]
    raise TypeError(f"unsupported canonical type: {type(value)!r}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize the constrained Aegis signing domain deterministically.

    This is deliberately narrower than general JSON. Every value carries a
    type tag so accepted semantic types cannot collide (for example Decimal(1)
    versus the string "1"). Floats are rejected, Unicode is NFC, and keys sort.
    """

    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
