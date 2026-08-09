"""Real-source SEC PIT builder; it only runs when invoked with a declared SEC identity."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from aegis.contracts import canonical_json
from aegis.sources.raw_store import RawStore

from .fundamentals import PITFundamentalFact, normalize_sec_facts
from .models import PITArtifact, SecurityMasterRecord
from .sec import SecPITClient

# The initial automatic corpus is statements-first. Event/ownership forms
# require an archive-index resolver because some SEC rows do not expose a
# stable primary-document route; callers may opt in after that resolver exists.
DEFAULT_FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A"})


class PITBuildError(RuntimeError):
    pass


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


def _append_immutable(path: Path, rows: tuple[PITArtifact, ...]) -> None:
    existing = path.read_text().splitlines() if path.exists() else []
    known = {PITArtifact.model_validate_json(row).artifact_id for row in existing if row}
    additions = [canonical_json(row) for row in rows if row.artifact_id not in known]
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
    securities: list[SecurityMasterRecord] = []
    for ticker in requested:
        cik = mappings[ticker]
        filings = client.submissions(cik)
        securities.append(
            SecurityMasterRecord(
                canonical_security_id=f"sec:{cik}",
                ticker=ticker,
                cik=cik,
                issuer=ticker,
                valid_from=datetime(1900, 1, 1, tzinfo=UTC),
                source="SEC_EDGAR",
                source_version="company-tickers",
            )
        )
        for filing in filings:
            if (
                filing.form not in allowed_forms
                or (filing_start is not None and filing.filed_at.date() < filing_start)
                or (filing_end is not None and filing.filed_at.date() > filing_end)
            ):
                continue
            receipt = client.filing_document(filing)
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
                    available_at=filing.available_at,
                    ingested_at=receipt.fetched_at,
                    raw_path=receipt.raw_uri,
                    sha256=receipt.content_hash,
                    parser_version="sec-pit-v1",
                    metadata={"primary_document": filing.primary_document, "cik": cik},
                )
            )
        normalized_facts.extend(normalize_sec_facts(ticker, client.company_facts(cik)))
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
    security_path = lake / "normalized" / "security_master.jsonl"
    if not security_path.exists():
        security_path.write_text("".join(canonical_json(item) + "\n" for item in securities))
    return tuple(built)
