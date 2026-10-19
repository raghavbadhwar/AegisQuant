"""Versioned source-manifest registry."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import TypeAdapter

from aegis.contracts import SourceManifest


class SourceRegistryError(ValueError):
    pass


class SourceRegistry:
    def __init__(self, manifests: tuple[SourceManifest, ...]) -> None:
        ids = [manifest.source_id for manifest in manifests]
        if len(ids) != len(set(ids)):
            raise SourceRegistryError("duplicate source ID")
        self._items = {item.source_id: item for item in manifests}

    @classmethod
    def load(cls, root: str | Path) -> SourceRegistry:
        source_root = Path(root).resolve()
        manifests: list[SourceManifest] = []
        for path in sorted(source_root.glob("*.yaml")):
            try:
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                manifests.extend(TypeAdapter(list[SourceManifest]).validate_python(payload))
            except Exception as exc:
                raise SourceRegistryError(f"invalid source manifest file: {path}") from exc
        if not manifests:
            raise SourceRegistryError("source registry is empty")
        return cls(tuple(manifests))

    def get(self, source_id: str) -> SourceManifest:
        try:
            return self._items[source_id]
        except KeyError as exc:
            raise SourceRegistryError(f"unknown source: {source_id}") from exc

    def all(self) -> tuple[SourceManifest, ...]:
        return tuple(self._items[key] for key in sorted(self._items))
