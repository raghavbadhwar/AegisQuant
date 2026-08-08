"""Central point-in-time and mode policies."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from aegis.data.protocol import PointInTimeViolation


class HasAvailability(Protocol):
    available_at: datetime


def require_available(record: HasAvailability, as_of: datetime) -> None:
    if record.available_at > as_of:
        available = record.available_at.isoformat()
        cutoff = as_of.isoformat()
        raise PointInTimeViolation(f"record available at {available} is after as_of {cutoff}")


def filter_available[T: HasAvailability](records: list[T], as_of: datetime) -> list[T]:
    return [record for record in records if record.available_at <= as_of]
