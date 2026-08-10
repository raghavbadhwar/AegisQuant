"""Local append-only evidence index for candidate-only adaptive research."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from aegis.contracts import canonical_json, canonical_sha256
from aegis.contracts._base import CandidateContractModel

_SHA256 = r"^[0-9a-f]{64}$"
_GENESIS = "0" * 64
_MAX_RECORDS = 128


def _required_content_hash(value: str | None) -> str:
    if value is None:
        raise AdaptiveEvidenceIndexError("adaptive evidence record must be sealed")
    return value


class AdaptiveEvidenceIndexError(RuntimeError):
    """Raised when the local evidence index cannot verify its append-only lineage."""


class _SealedAdaptiveEvidenceModel(CandidateContractModel):
    content_hash: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def has_valid_content_hash(self) -> Self:
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("adaptive evidence content hash mismatch")
        return self

    def sealed(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = type(self).model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class AdaptiveEvidenceRecord(_SealedAdaptiveEvidenceModel):
    """One receipt-referenced local evidence item, never an authenticity assertion."""

    evidence_id: str = Field(min_length=1)
    record_kind: Literal["verification", "negative_result", "refutation"]
    payload: dict[str, str] = Field(min_length=1)
    payload_content_hash: str = Field(pattern=_SHA256)
    receipt_id: str = Field(min_length=1)
    receipt_payload: dict[str, str] = Field(min_length=1)
    receipt_content_hash: str = Field(pattern=_SHA256)
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def binds_exact_payload(self) -> AdaptiveEvidenceRecord:
        if any(not key or not value for key, value in self.payload.items()):
            raise ValueError("adaptive evidence payload keys and values must be nonempty")
        if canonical_sha256(self.payload) != self.payload_content_hash:
            raise ValueError("adaptive evidence payload content hash mismatch")
        if canonical_sha256(self.receipt_payload) != self.receipt_content_hash:
            raise ValueError("adaptive evidence receipt content hash mismatch")
        if self.receipt_payload.get("receipt_id") != self.receipt_id:
            raise ValueError("adaptive evidence receipt payload ID mismatch")
        receipt_observed_at = self.receipt_payload.get("observed_at")
        if receipt_observed_at is None:
            raise ValueError("adaptive evidence receipt observed time is required")
        try:
            parsed_observed_at = datetime.fromisoformat(receipt_observed_at)
        except ValueError as exc:
            raise ValueError("adaptive evidence receipt observed time is invalid") from exc
        if parsed_observed_at.tzinfo is None or parsed_observed_at != self.observed_at:
            raise ValueError("adaptive evidence receipt observed time mismatch")
        return self


class AdaptiveEvidenceCheckpoint(_SealedAdaptiveEvidenceModel):
    """Sealed local checkpoint root for evidence available by one observed-time cutoff."""

    as_of: AwareDatetime
    sequence: int = Field(ge=1, le=_MAX_RECORDS)
    record_ids: tuple[str, ...] = Field(min_length=1)
    record_hashes: tuple[str, ...] = Field(min_length=1)
    commitment_hash: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def has_unique_records(self) -> AdaptiveEvidenceCheckpoint:
        if len(self.record_ids) != self.sequence or len(self.record_hashes) != self.sequence:
            raise ValueError("adaptive evidence checkpoint sequence does not reconcile")
        if len(set(self.record_ids)) != len(self.record_ids):
            raise ValueError("adaptive evidence checkpoint record IDs must be unique")
        return self


class AdaptiveEvidenceIndex:
    """Fixture-scale SQLite index with a verified append-only commitment chain.

    This is local consistency evidence only. It is not external receipt custody,
    authenticated provenance, or a claim of complete historical evidence.
    """

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path).resolve()
        self.read_only = read_only
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            return sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
        return sqlite3.connect(self.path)

    @staticmethod
    def _commitment_hash(
        sequence: int, evidence_id: str, record_hash: str, previous_hash: str
    ) -> str:
        return canonical_sha256(
            {
                "sequence": sequence,
                "evidence_id": evidence_id,
                "record_hash": record_hash,
                "previous_commitment_hash": previous_hash,
            }
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS adaptive_evidence_records (
                    evidence_id TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL,
                    record_hash TEXT NOT NULL UNIQUE,
                    observed_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS adaptive_evidence_commitments (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    evidence_id TEXT NOT NULL UNIQUE,
                    record_hash TEXT NOT NULL UNIQUE,
                    previous_commitment_hash TEXT NOT NULL,
                    commitment_hash TEXT NOT NULL UNIQUE
                )"""
            )
            connection.executescript(
                """CREATE TRIGGER IF NOT EXISTS adaptive_evidence_records_no_update
                   BEFORE UPDATE ON adaptive_evidence_records
                   BEGIN SELECT RAISE(ABORT, 'adaptive evidence index is append-only'); END;
                   CREATE TRIGGER IF NOT EXISTS adaptive_evidence_records_no_delete
                   BEFORE DELETE ON adaptive_evidence_records
                   BEGIN SELECT RAISE(ABORT, 'adaptive evidence index is append-only'); END;
                   CREATE TRIGGER IF NOT EXISTS adaptive_evidence_commitments_no_update
                   BEFORE UPDATE ON adaptive_evidence_commitments
                   BEGIN SELECT RAISE(ABORT, 'adaptive evidence index is append-only'); END;
                   CREATE TRIGGER IF NOT EXISTS adaptive_evidence_commitments_no_delete
                   BEFORE DELETE ON adaptive_evidence_commitments
                   BEGIN SELECT RAISE(ABORT, 'adaptive evidence index is append-only'); END;"""
            )

    def _records_and_commitments(
        self, connection: sqlite3.Connection
    ) -> list[tuple[int, AdaptiveEvidenceRecord, str]]:
        rows = connection.execute(
            """SELECT c.sequence, c.evidence_id, c.record_hash, c.previous_commitment_hash,
                      c.commitment_hash, r.record_json, r.record_hash
               FROM adaptive_evidence_commitments c
               LEFT JOIN adaptive_evidence_records r ON r.evidence_id = c.evidence_id
               ORDER BY c.sequence"""
        ).fetchall()
        previous_hash = _GENESIS
        validated: list[tuple[int, AdaptiveEvidenceRecord, str]] = []
        prior_observed_at: AwareDatetime | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            (
                sequence,
                evidence_id,
                record_hash,
                recorded_previous,
                commitment_hash,
                record_json,
                stored_record_hash,
            ) = row
            if (
                sequence != expected_sequence
                or record_json is None
                or stored_record_hash != record_hash
                or recorded_previous != previous_hash
            ):
                raise AdaptiveEvidenceIndexError("adaptive evidence commitment chain mismatch")
            expected_commitment = self._commitment_hash(
                sequence, evidence_id, record_hash, previous_hash
            )
            if commitment_hash != expected_commitment:
                raise AdaptiveEvidenceIndexError("adaptive evidence commitment hash mismatch")
            try:
                record = AdaptiveEvidenceRecord.model_validate_json(record_json)
            except ValueError as exc:
                raise AdaptiveEvidenceIndexError("adaptive evidence record is invalid") from exc
            if record.content_hash != record_hash or record.evidence_id != evidence_id:
                raise AdaptiveEvidenceIndexError("adaptive evidence record was replaced")
            if prior_observed_at is not None and record.observed_at < prior_observed_at:
                raise AdaptiveEvidenceIndexError(
                    "adaptive evidence observed times are not chronological"
                )
            validated.append((sequence, record, commitment_hash))
            previous_hash = commitment_hash
            prior_observed_at = record.observed_at
        count = connection.execute("SELECT COUNT(*) FROM adaptive_evidence_records").fetchone()[0]
        if count != len(validated):
            raise AdaptiveEvidenceIndexError(
                "adaptive evidence records and commitments do not reconcile"
            )
        return validated

    def append(self, record: AdaptiveEvidenceRecord) -> AdaptiveEvidenceCheckpoint:
        if self.read_only:
            raise AdaptiveEvidenceIndexError("adaptive evidence index is read-only")
        try:
            validated = AdaptiveEvidenceRecord.model_validate(record.model_dump(mode="json"))
        except ValueError as exc:
            raise AdaptiveEvidenceIndexError("adaptive evidence record is invalid") from exc
        if validated.content_hash is None:
            raise AdaptiveEvidenceIndexError("adaptive evidence record must be sealed")
        payload = canonical_json(validated)
        with self._connect() as connection:
            existing_records = self._records_and_commitments(connection)
            existing = connection.execute(
                """SELECT record_json, record_hash FROM adaptive_evidence_records
                   WHERE evidence_id = ?""",
                (validated.evidence_id,),
            ).fetchone()
            if existing is not None:
                if existing != (payload, validated.content_hash):
                    raise AdaptiveEvidenceIndexError(
                        "adaptive evidence ID already has different content"
                    )
                return self._checkpoint_from(existing_records, validated.observed_at)
            if len(existing_records) >= _MAX_RECORDS:
                raise AdaptiveEvidenceIndexError(
                    "adaptive evidence fixture-scale record limit exceeded"
                )
            if existing_records and validated.observed_at < existing_records[-1][1].observed_at:
                raise AdaptiveEvidenceIndexError(
                    "adaptive evidence observed time cannot be backfilled"
                )
            previous_hash = existing_records[-1][2] if existing_records else _GENESIS
            sequence = len(existing_records) + 1
            commitment_hash = self._commitment_hash(
                sequence, validated.evidence_id, validated.content_hash, previous_hash
            )
            connection.execute(
                """INSERT INTO adaptive_evidence_records
                   (evidence_id, record_json, record_hash, observed_at) VALUES (?, ?, ?, ?)""",
                (
                    validated.evidence_id,
                    payload,
                    validated.content_hash,
                    validated.observed_at.isoformat(),
                ),
            )
            connection.execute(
                """INSERT INTO adaptive_evidence_commitments
                   (evidence_id, record_hash, previous_commitment_hash, commitment_hash)
                   VALUES (?, ?, ?, ?)""",
                (validated.evidence_id, validated.content_hash, previous_hash, commitment_hash),
            )
            return self._checkpoint_from(
                [*existing_records, (sequence, validated, commitment_hash)], validated.observed_at
            )

    @staticmethod
    def _checkpoint_from(
        records: list[tuple[int, AdaptiveEvidenceRecord, str]], as_of: AwareDatetime
    ) -> AdaptiveEvidenceCheckpoint:
        eligible = [item for item in records if item[1].observed_at <= as_of]
        if not eligible:
            raise AdaptiveEvidenceIndexError("adaptive evidence checkpoint has no eligible records")
        sequence, _, commitment_hash = eligible[-1]
        return AdaptiveEvidenceCheckpoint(
            as_of=as_of,
            sequence=sequence,
            record_ids=tuple(record.evidence_id for _, record, _ in eligible),
            record_hashes=tuple(
                _required_content_hash(record.content_hash) for _, record, _ in eligible
            ),
            commitment_hash=commitment_hash,
        ).sealed()

    def checkpoint(self, as_of: AwareDatetime) -> AdaptiveEvidenceCheckpoint:
        with self._connect() as connection:
            return self._checkpoint_from(self._records_and_commitments(connection), as_of)

    def resolve(
        self,
        *,
        as_of: AwareDatetime,
        record_kinds: tuple[Literal["verification", "negative_result", "refutation"], ...],
    ) -> tuple[AdaptiveEvidenceRecord, ...]:
        """Resolve one versioned local evidence subset without caller ordering."""

        if not record_kinds or len(record_kinds) != len(set(record_kinds)):
            raise AdaptiveEvidenceIndexError(
                "adaptive evidence record kinds must be nonempty and unique"
            )
        with self._connect() as connection:
            records = self._records_and_commitments(connection)
        resolved = [
            record
            for _, record, _ in records
            if record.observed_at <= as_of and record.record_kind in record_kinds
        ]
        return tuple(sorted(resolved, key=lambda record: record.evidence_id))
