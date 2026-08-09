"""Availability-gated PIT query layer and deterministic offline snapshot writer."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from aegis.contracts import canonical_json

from .models import PITArtifact, PITSnapshotManifest, SecurityMasterRecord
from .nport import NPortHolding


class PITLedgerError(RuntimeError):
    pass


class PITAvailabilityLedger:
    """In-memory immutable record index; all historical queries apply the time gate."""

    def __init__(
        self, artifacts: tuple[PITArtifact, ...], securities: tuple[SecurityMasterRecord, ...] = ()
    ) -> None:
        identifiers = [item.artifact_id for item in artifacts]
        if len(identifiers) != len(set(identifiers)):
            raise PITLedgerError("PIT artifact identifiers must be unique")
        self.artifacts = tuple(
            sorted(artifacts, key=lambda item: (item.available_at, item.artifact_id))
        )
        self.securities = tuple(sorted(securities, key=lambda item: item.canonical_security_id))

    @staticmethod
    def _cutoff(at: datetime) -> datetime:
        if at.tzinfo is None or at.utcoffset() is None:
            raise PITLedgerError("simulation timestamp must be timezone-aware")
        return at

    def get_artifacts_as_of(
        self, at: datetime, universe: tuple[str, ...] | None = None
    ) -> tuple[PITArtifact, ...]:
        cutoff = self._cutoff(at)
        allowed = set(universe) if universe is not None else None
        return tuple(
            item
            for item in self.artifacts
            if item.available_at <= cutoff
            and (allowed is None or item.entity_id in allowed or item.security_id in allowed)
        )

    def get_filings_as_of(self, entity_id: str, at: datetime) -> tuple[PITArtifact, ...]:
        return tuple(
            item
            for item in self.get_artifacts_as_of(at)
            if item.entity_id == entity_id and item.source == "SEC_EDGAR"
        )

    def write_snapshot(
        self,
        root: str | Path,
        at: datetime,
        universe: tuple[str, ...],
        *,
        dataset_version: str,
        warnings: tuple[str, ...] = (),
        fund_holdings: tuple[NPortHolding, ...] = (),
    ) -> Path:
        cutoff = self._cutoff(at)
        selected = self.get_artifacts_as_of(cutoff, universe)
        selected_holdings = tuple(
            item for item in fund_holdings if item.public_available_at <= cutoff
        )
        if any(item.available_at > cutoff for item in selected):
            raise PITLedgerError("future artifact contamination")
        if any(item.public_available_at > cutoff for item in selected_holdings):
            raise PITLedgerError("future fund-holding contamination")
        name = cutoff.astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
        destination = Path(root).resolve() / name
        if destination.exists():
            raise PITLedgerError("snapshot destination already exists and is immutable")
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = PITSnapshotManifest(
            simulation_at=cutoff,
            built_at=datetime.now(UTC),
            artifact_count=len(selected),
            universe=tuple(sorted(set(universe))),
            artifact_ids=tuple(item.artifact_id for item in selected),
            artifact_hashes=tuple(item.sha256 for item in selected),
            dataset_version=dataset_version,
            parser_versions=tuple(sorted({item.parser_version for item in selected})),
            warnings=warnings,
        ).sealed()
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        temporary.mkdir()
        (temporary / "manifest.json").write_text(canonical_json(manifest) + "\n")
        (temporary / "artifacts.jsonl").write_text(
            "".join(canonical_json(item) + "\n" for item in selected)
        )
        security_rows = [
            item
            for item in self.securities
            if item.valid_from <= cutoff
            and (item.valid_to is None or cutoff <= item.valid_to)
            and item.canonical_security_id in set(universe)
        ]
        (temporary / "security_master.jsonl").write_text(
            "".join(canonical_json(item) + "\n" for item in security_rows)
        )
        (temporary / "fund_holdings.jsonl").write_text(
            "".join(canonical_json(item) + "\n" for item in selected_holdings)
        )
        os.replace(temporary, destination)
        return destination


def load_snapshot(path: str | Path) -> tuple[PITSnapshotManifest, tuple[PITArtifact, ...]]:
    root = Path(path).resolve()
    try:
        manifest = PITSnapshotManifest.model_validate_json((root / "manifest.json").read_bytes())
        rows = tuple(
            PITArtifact.model_validate_json(line)
            for line in (root / "artifacts.jsonl").read_text().splitlines()
            if line
        )
    except Exception as exc:
        raise PITLedgerError(f"invalid PIT snapshot: {path}") from exc
    if any(item.available_at > manifest.simulation_at for item in rows):
        raise PITLedgerError("snapshot contains future artifact")
    if tuple(item.artifact_id for item in rows) != manifest.artifact_ids:
        raise PITLedgerError("snapshot artifact lineage mismatch")
    return manifest, rows
