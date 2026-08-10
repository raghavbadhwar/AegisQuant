"""Real-source SEC PIT builder; it only runs when invoked with a declared SEC identity."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from aegis.contracts import FetchedDocument, RawDocumentReceipt, canonical_json
from aegis.sources.raw_store import RawStore

from .fundamentals import PITFundamentalFact, normalize_sec_facts
from .ledger import PITAvailabilityLedger
from .models import PITArtifact, SecurityMasterRecord
from .nport import NPortHolding, normalize_nport_holdings
from .sec import SecPITClient, archived_acceptance_time, parse_archived_xbrl_facts

# The initial automatic corpus is statements-first. Event/ownership forms
# require an archive-index resolver because some SEC rows do not expose a
# stable primary-document route; callers may opt in after that resolver exists.
DEFAULT_FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A"})


class PITBuildError(RuntimeError):
    pass


class _SecurityMasterImportRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: str = Field(min_length=1)
    canonical_security_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    cik: str | None = Field(default=None, pattern=r"^\d{10}$")
    cusip: str | None = None
    issuer: str = Field(min_length=1)
    exchange: str | None = None
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None = None


class _SecurityMasterImport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_available_at: AwareDatetime
    records: tuple[_SecurityMasterImportRow, ...] = Field(min_length=1)


def _require_receipt_body(receipt: RawDocumentReceipt, body: bytes) -> None:
    if receipt.byte_length != len(body) or receipt.content_hash != hashlib.sha256(body).hexdigest():
        raise PITBuildError("SEC raw receipt does not match submission bytes")


def bootstrap(root: str | Path) -> Path:
    """Create the local-only PIT lake layout; never downloads data."""
    path = Path(root).resolve()
    for name in ("raw/sec", "normalized", "snapshots"):
        (path / name).mkdir(parents=True, exist_ok=True)
    readme = path / "README.md"
    if not readme.exists():
        readme.write_text(
            "# AegisQuant PIT Data Lake\n\n"
            "Generated local artifacts are immutable. Synthetic data is prohibited "
            "as release or performance evidence.\n"
        )
    return path


def import_security_master(
    root: str | Path, source_path: str | Path
) -> tuple[SecurityMasterRecord, ...]:
    """Import explicit dated mappings from one retained, content-addressed local source."""
    source = Path(source_path).resolve()
    try:
        body = source.read_bytes()
        envelope = _SecurityMasterImport.model_validate_json(body)
    except (OSError, ValueError) as exc:
        raise PITBuildError("invalid dated security-master source") from exc
    if len(body) > 25_000_000:
        raise PITBuildError("dated security-master source exceeds import limit")
    source_record_ids = [item.source_record_id for item in envelope.records]
    if len(source_record_ids) != len(set(source_record_ids)):
        raise PITBuildError("duplicate security-master source record")
    lake = bootstrap(root)
    receipt = RawStore(lake / "raw").commit(
        FetchedDocument(
            source_id=envelope.source,
            request_id=f"security-master-{envelope.source_version}",
            url=source.as_uri(),
            connector="security-master-import-v1",
            connector_version="security-master-import-v1",
            status_code=200,
            headers={"content-type": "application/json"},
            body=body,
            fetched_at=datetime.now(UTC),
            media_type="application/json",
        )
    )
    records = tuple(
        SecurityMasterRecord(
            **row.model_dump(),
            source=envelope.source,
            source_version=envelope.source_version,
            source_available_at=envelope.source_available_at,
            source_content_hash=receipt.content_hash,
            source_raw_uri=receipt.raw_uri,
        )
        for row in envelope.records
    )
    path = lake / "normalized" / "security_master.jsonl"
    existing = (
        tuple(
            SecurityMasterRecord.model_validate_json(line)
            for line in path.read_text().splitlines()
            if line
        )
        if path.exists()
        else ()
    )
    known = {item.source_record_id: item for item in existing}
    if len(known) != len(existing):
        raise PITBuildError("duplicate security-master source record")
    additions: list[SecurityMasterRecord] = []
    for record in records:
        previous = known.get(record.source_record_id)
        if previous is not None:
            if previous != record:
                raise PITBuildError("conflicting immutable security-master record")
            continue
        known[record.source_record_id] = record
        additions.append(record)
    PITAvailabilityLedger((), tuple(known.values()))
    if additions:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write("".join(canonical_json(item) + "\n" for item in additions))
    return records


def _append_immutable(path: Path, rows: tuple[PITArtifact, ...]) -> None:
    existing = path.read_text().splitlines() if path.exists() else []
    known: dict[str, PITArtifact] = {}
    for raw_row in existing:
        if not raw_row:
            continue
        artifact = PITArtifact.model_validate_json(raw_row)
        if artifact.artifact_id in known:
            raise PITBuildError(f"conflicting immutable artifact: {artifact.artifact_id}")
        known[artifact.artifact_id] = artifact
    additions: list[str] = []
    for row in rows:
        previous = known.get(row.artifact_id)
        if previous is not None:
            if previous.model_dump(exclude={"ingested_at"}) != row.model_dump(
                exclude={"ingested_at"}
            ):
                raise PITBuildError(f"conflicting immutable artifact: {row.artifact_id}")
            continue
        known[row.artifact_id] = row
        additions.append(canonical_json(row))
    if additions:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write("".join(value + "\n" for value in additions))


def ingest_sec(
    root: str | Path,
    user_agent: str,
    tickers: tuple[str, ...],
    *,
    allowed_forms: frozenset[str] = DEFAULT_FORMS,
    filing_start: date | None = None,
    filing_end: date | None = None,
) -> tuple[PITArtifact, ...]:
    """Download official SEC filing evidence and append non-mutating ledger rows."""
    if filing_start is not None and filing_end is not None and filing_end < filing_start:
        raise PITBuildError("SEC filing end must not precede filing start")
    lake = bootstrap(root)
    client = SecPITClient(user_agent, RawStore(lake / "raw"))
    mappings = client.ticker_cik_map()
    requested = tuple(sorted({ticker.upper() for ticker in tickers}))
    missing = sorted(set(requested).difference(mappings))
    if missing:
        raise PITBuildError(f"SEC ticker/CIK mapping missing: {', '.join(missing)}")
    built: list[PITArtifact] = []
    normalized_facts: list[PITFundamentalFact] = []
    for ticker in requested:
        cik = mappings[ticker]
        filings = client.submissions(cik)
        for filing in filings:
            if (
                filing.form not in allowed_forms
                or (filing_start is not None and filing.filed_at.date() < filing_start)
                or (filing_end is not None and filing.filed_at.date() > filing_end)
            ):
                continue
            receipt, submission = client.filing_submission(filing)
            _require_receipt_body(receipt, submission)
            accepted_at = archived_acceptance_time(submission, filing)
            facts = parse_archived_xbrl_facts(filing, submission)
            normalized_facts.extend(normalize_sec_facts(ticker, facts))
            built.append(
                PITArtifact(
                    artifact_id=f"sec:{cik}:{filing.accession_number}",
                    source="SEC_EDGAR",
                    source_record_id=filing.accession_number,
                    entity_id=ticker,
                    security_id=f"sec:{cik}",
                    artifact_type="filing",
                    form=filing.form,
                    accession=filing.accession_number,
                    period_end=filing.period_end,
                    filed_at=filing.filed_at,
                    accepted_at=accepted_at,
                    available_at=accepted_at,
                    ingested_at=receipt.fetched_at,
                    raw_path=receipt.raw_uri,
                    sha256=receipt.content_hash,
                    parser_version="sec-archived-xbrl-v1",
                    metadata={"primary_document": filing.primary_document, "cik": cik},
                )
            )
    _append_immutable(lake / "normalized" / "artifact_ledger.jsonl", tuple(built))
    facts_path = lake / "normalized" / "fundamental_fact_versions.jsonl"
    known_fact_versions = set(facts_path.read_text().splitlines()) if facts_path.exists() else set()
    new_fact_rows = [canonical_json(item) for item in normalized_facts]
    if new_fact_rows:
        facts_path.parent.mkdir(parents=True, exist_ok=True)
        with facts_path.open("a") as handle:
            handle.write(
                "".join(item + "\n" for item in new_fact_rows if item not in known_fact_versions)
            )
    return tuple(built)


def normalize_nport(
    root: str | Path,
    archive_path: str | Path,
    *,
    raw_artifact_id: str,
    series_ids: frozenset[str],
) -> tuple[NPortHolding, ...]:
    """Persist selected real N-PORT rows; source zip remains immutable in raw store."""
    lake = bootstrap(root)
    rows = normalize_nport_holdings(
        archive_path, raw_artifact_id=raw_artifact_id, series_ids=series_ids
    )
    output = lake / "normalized" / "nport_holdings.jsonl"
    existing = set(output.read_text().splitlines()) if output.exists() else set()
    additions = [canonical_json(item) for item in rows]
    if additions:
        with output.open("a") as handle:
            handle.write("".join(item + "\n" for item in additions if item not in existing))
    return rows
