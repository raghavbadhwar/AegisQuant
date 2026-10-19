"""Optional GBrain projection/ranking adapter; local memory remains authoritative."""

from __future__ import annotations

from typing import Protocol

from aegis.contracts import MemoryHit, MemoryItem, MemoryQuery

from .local_backend import LocalMemoryBackend


class GBrainClient(Protocol):
    def project(self, item: MemoryItem) -> None: ...

    def search_ids(self, query: str, top_k: int) -> list[str]: ...


class GBrainMemoryAdapter:
    def __init__(self, local: LocalMemoryBackend, client: GBrainClient) -> None:
        self.local = local
        self.client = client

    def project(self, item: MemoryItem) -> bool:
        try:
            self.client.project(item)
        except Exception:
            return False
        return True

    def search(self, query: MemoryQuery) -> tuple[MemoryHit, ...]:
        local_hits = self.local.search(query.model_copy(update={"top_k": 100}))
        try:
            ranked_ids = self.client.search_ids(query.text, query.top_k)
        except Exception:
            return local_hits[: query.top_k]
        by_id = {hit.item.memory_id: hit for hit in local_hits}
        reranked = [by_id[memory_id] for memory_id in ranked_ids if memory_id in by_id]
        seen = {hit.item.memory_id for hit in reranked}
        reranked.extend(hit for hit in local_hits if hit.item.memory_id not in seen)
        return tuple(reranked[: query.top_k])
