"""Optional memory-backend protocol."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from aegis.contracts import MemoryHit, MemoryQuery, MemorySnapshot


class MemoryReader(Protocol):
    def search(self, query: MemoryQuery) -> tuple[MemoryHit, ...]: ...

    def snapshot(self, as_of: datetime) -> MemorySnapshot: ...
