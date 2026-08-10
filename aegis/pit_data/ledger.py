"""Availability-gated PIT query layer and deterministic offline snapshot writer."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from aegis.contracts import canonical_json, canonical_sha256

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
        for attribute in ("ticker", "canonical_security_id"):
            ordered = sorted(
                securities,
                key=lambda item: (getattr(item, attribute), item.valid_from, item.source_record_id),
            )
            for previous, current in pairwise(ordered):
                if getattr(previous, attribute) != getattr(current, attribute):
                    continue
                if previous.valid_to is None or current.valid_from <= previous.valid_to:
                    raise PITLedgerError("overlapping security mapping history")
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
        universe_set = set(universe)
        security_rows = [
            item
            for item in self.securities
            if item.source_available_at <= cutoff
            and item.valid_from <= cutoff
            and (item.valid_to is None or cutoff <= item.valid_to)
            and (item.canonical_security_id in universe_set or item.ticker in universe_set)
        ]
        mapped = {item.ticker for item in security_rows}.union(
            item.canonical_security_id for item in security_rows
        )
        if not universe_set.issubset(mapped):
            raise PITLedgerError("snapshot lacks applicable historical security mapping")
        security_sources: dict[str, bytes] = {}
        for item in security_rows:
            try:
                source_bytes = Path(item.source_raw_uri).read_bytes()
            except OSError as exc:
                raise PITLedgerError("security source is unavailable") from exc
            if hashlib.sha256(source_bytes).hexdigest() != item.source_content_hash:
                raise PITLedgerError("security source hash mismatch")
            security_sources[item.source_content_hash] = source_bytes
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = PITSnapshotManifest(
            simulation_at=cutoff,
            built_at=datetime.now(UTC),
            artifact_count=len(selected),
            universe=tuple(sorted(set(universe))),
            artifact_ids=tuple(item.artifact_id for item in selected),
            artifact_hashes=tuple(item.sha256 for item in selected),
            security_record_ids=tuple(item.source_record_id for item in security_rows),
            security_record_hashes=tuple(canonical_sha256(item) for item in security_rows),
            dataset_version=dataset_version,
            parser_versions=tuple(sorted({item.parser_version for item in selected})),
            warnings=warnings,
        ).sealed()
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        temporary.mkdir()
        (temporary / "security_sources").mkdir()
        for digest, source_bytes in security_sources.items():
            (temporary / "security_sources" / f"{digest}.bin").write_bytes(source_bytes)
        (temporary / "manifest.json").write_text(canonical_json(manifest) + "\n")
        (temporary / "artifacts.jsonl").write_text(
            "".join(canonical_json(item) + "\n" for item in selected)
        )
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
        securities = tuple(
            SecurityMasterRecord.model_validate_json(line)
            for line in (root / "security_master.jsonl").read_text().splitlines()
            if line
        )
    except Exception as exc:
        raise PITLedgerError(f"invalid PIT snapshot: {path}") from exc
    universe = set(manifest.universe)
    mapped = {item.ticker for item in securities}.union(
        item.canonical_security_id for item in securities
    )
    if not universe.issubset(mapped):
        raise PITLedgerError("snapshot lacks applicable historical security mappings")
    if any(
        item.valid_from > manifest.simulation_at
        or item.source_available_at > manifest.simulation_at
        or (item.valid_to is not None and item.valid_to < manifest.simulation_at)
        for item in securities
    ):
        raise PITLedgerError("snapshot security mapping is not valid at its cutoff")
    if any(item.available_at > manifest.simulation_at for item in rows):
        raise PITLedgerError("snapshot contains future artifact")
    if tuple(item.artifact_id for item in rows) != manifest.artifact_ids:
        raise PITLedgerError("snapshot artifact lineage mismatch")
    if tuple(item.sha256 for item in rows) != manifest.artifact_hashes:
        raise PITLedgerError("snapshot artifact hash mismatch")
    if tuple(item.source_record_id for item in securities) != manifest.security_record_ids:
        raise PITLedgerError("snapshot security mapping lineage mismatch")
    if tuple(canonical_sha256(item) for item in securities) != manifest.security_record_hashes:
        raise PITLedgerError("snapshot security mapping hash mismatch")
    for item in securities:
        try:
            source_bytes = (
                root / "security_sources" / f"{item.source_content_hash}.bin"
            ).read_bytes()
        except OSError as exc:
            raise PITLedgerError("snapshot security source hash mismatch") from exc
        if hashlib.sha256(source_bytes).hexdigest() != item.source_content_hash:
            raise PITLedgerError("snapshot security source hash mismatch")
    PITAvailabilityLedger((), securities)
    return manifest, rows
